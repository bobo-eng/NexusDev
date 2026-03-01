"""Worker for asynchronous task execution.

Handles:
- Background stage execution
- Retry logic
- Timeout handling
- Progress reporting
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from core.domain.stage import Stage, StageStatus
from core.services.stage_service import StageService
from core.services.approval_service import ApprovalService
from core.storage.database import Database, create_database
from core.storage.models import StageModel

logger = logging.getLogger(__name__)


class Worker:
    """Asynchronous worker for stage execution.
    
    The worker:
    1. Polls for pending stages
    2. Executes stages using appropriate agents
    3. Handles retries and timeouts
    4. Reports progress
    """
    
    def __init__(self, database: Database | None = None):
        self.database = database or create_database()
        self.stage_service = StageService(self.database)
        self.approval_service = ApprovalService(self.database)
        self._running = False
        self._task: asyncio.Task | None = None
        self._poll_interval = 5  # seconds
        self._max_concurrent = 4
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
    
    async def start(self) -> None:
        """Start the worker."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Worker started")
    
    async def stop(self) -> None:
        """Stop the worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Worker stopped")
    
    async def _run_loop(self) -> None:
        """Main worker loop."""
        while self._running:
            try:
                # Process pending stages
                await self._process_pending_stages()
                
                # Check for timeouts
                await self._check_timeouts()
                
                # Check approval timeouts
                await self._check_approval_timeouts()
                
                # Wait before next poll
                await asyncio.sleep(self._poll_interval)
                
            except Exception as e:
                logger.error(f"Worker error: {e}")
                await asyncio.sleep(10)
    
    async def _process_pending_stages(self) -> None:
        """Process pending stages."""
        async with self.database.session() as db_session:
            # Query for pending stages
            result = await db_session.execute(
                select(StageModel)
                .where(StageModel.status == StageStatus.PENDING.value)
                .order_by(StageModel.created_at)
                .limit(self._max_concurrent)
            )
            pending_stages = result.scalars().all()
        
        if not pending_stages:
            return
        
        logger.info(f"Found {len(pending_stages)} pending stages")
        
        # Execute stages concurrently (with semaphore limit)
        tasks = []
        for stage_model in pending_stages:
            stage = Stage.model_validate(stage_model)
            task = asyncio.create_task(
                self._execute_with_semaphore(stage)
            )
            tasks.append(task)
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _execute_with_semaphore(self, stage: Stage) -> None:
        """Execute stage with semaphore control."""
        async with self._semaphore:
            await self.execute_stage(stage.id, stage.context)
    
    async def _check_timeouts(self) -> None:
        """Check for timed out stages."""
        timeout_threshold = datetime.utcnow() - timedelta(minutes=30)  # Default 30 min timeout
        
        async with self.database.session() as db_session:
            # Query for running stages that have timed out
            result = await db_session.execute(
                select(StageModel)
                .where(StageModel.status == StageStatus.RUNNING.value)
                .where(StageModel.started_at < timeout_threshold)
            )
            timed_out_stages = result.scalars().all()
        
        for stage_model in timed_out_stages:
            stage = Stage.model_validate(stage_model)
            logger.warning(f"Stage {stage.id} timed out")
            
            # Mark as failed
            await self.stage_service.update_stage_status(
                stage.id,
                StageStatus.FAILED,
                error_message="Stage timed out after 30 minutes",
            )
    
    async def _check_approval_timeouts(self) -> None:
        """Check for timed out approvals."""
        timed_out = await self.approval_service.check_timeouts()
        if timed_out:
            logger.info(f"{len(timed_out)} approvals timed out")
            for approval in timed_out:
                logger.warning(
                    f"Approval {approval.id} for session {approval.session_id} timed out"
                )
    
    async def execute_stage(
        self,
        stage_id: UUID,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a stage.
        
        Args:
            stage_id: Stage ID
            context: Execution context
            
        Returns:
            Execution result
        """
        logger.info(f"Executing stage {stage_id}")
        
        # Get stage
        stage = await self.stage_service.get_stage(stage_id)
        if not stage:
            return {"error": "Stage not found"}
        
        # Skip if not in pending status
        if stage.status != StageStatus.PENDING:
            logger.info(f"Stage {stage_id} is not pending (status: {stage.status.value})")
            return {"stage_id": str(stage_id), "status": stage.status.value}
        
        # Update status to running
        await self.stage_service.update_stage_status(
            stage_id,
            StageStatus.RUNNING,
        )
        
        try:
            # Execute based on agent type
            result = await self._execute_agent(stage.agent_name, context)
            
            # Update status to completed
            await self.stage_service.update_stage_status(
                stage_id,
                StageStatus.COMPLETED,
                result=result,
            )
            
            logger.info(f"Stage {stage_id} completed successfully")
            
            return {
                "stage_id": str(stage_id),
                "status": "completed",
                "result": result,
            }
            
        except Exception as e:
            logger.error(f"Stage {stage_id} execution failed: {e}")
            
            # Check if can retry
            if stage.can_retry():
                logger.info(f"Stage {stage_id} will be retried ({stage.retry_count + 1}/{stage.max_retries})")
                await self.stage_service.retry_stage(stage_id)
                return {
                    "stage_id": str(stage_id),
                    "status": "retrying",
                    "error": str(e),
                }
            
            # Update status to failed
            await self.stage_service.update_stage_status(
                stage_id,
                StageStatus.FAILED,
                error_message=str(e),
            )
            
            return {
                "stage_id": str(stage_id),
                "status": "failed",
                "error": str(e),
            }
    
    async def _execute_agent(
        self,
        agent_name: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute an agent.
        
        Args:
            agent_name: Name of agent to execute
            context: Execution context
            
        Returns:
            Agent output
        """
        # Map agent names to agent classes
        agents = {
            "pm_agent": "core.agents.pm_agent.PMAgent",
            "architect_agent": "core.agents.architect_agent.ArchitectAgent",
            "coder_agent": "core.agents.coder_agent.CoderAgent",
            "reviewer_agent": "core.agents.reviewer_agent.ReviewerAgent",
            "tester_agent": "core.agents.tester_agent.TesterAgent",
        }
        
        agent_class = agents.get(agent_name)
        if not agent_class:
            raise ValueError(f"Unknown agent: {agent_name}")
        
        # Dynamic import
        module_path, class_name = agent_class.rsplit(".", 1)
        module = __import__(module_path, fromlist=[class_name])
        AgentClass = getattr(module, class_name)
        
        # Create and execute agent
        agent = AgentClass()
        result = await agent.execute(context)
        
        return result.model_dump()
    
    async def retry_stage(self, stage_id: UUID) -> dict[str, Any]:
        """Retry a failed stage.
        
        Args:
            stage_id: Stage ID
            
        Returns:
            Retry result
        """
        stage = await self.stage_service.retry_stage(stage_id)
        if not stage:
            return {"error": "Stage cannot be retried"}
        
        return {
            "stage_id": str(stage_id),
            "retry_count": stage.retry_count,
            "max_retries": stage.max_retries,
            "status": "pending",
        }


async def main():
    """Main entry point for worker."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    worker = Worker()
    await worker.start()
    
    try:
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await worker.stop()


if __name__ == "__main__":
    asyncio.run(main())
