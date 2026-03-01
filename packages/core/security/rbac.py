"""Role-Based Access Control (RBAC) for approval workflow.

Defines:
- Roles: admin, tech_lead, developer, viewer
- Permissions: create, read, update, delete, approve, reject
"""

from enum import Enum, auto
from functools import wraps
from typing import Callable


class Permission(str, Enum):
    """Permissions in the system."""
    
    SESSION_CREATE = "session:create"
    SESSION_READ = "session:read"
    SESSION_UPDATE = "session:update"
    SESSION_DELETE = "session:delete"
    
    STAGE_EXECUTE = "stage:execute"
    STAGE_READ = "stage:read"
    
    APPROVAL_APPROVE = "approval:approve"
    APPROVAL_REJECT = "approval:reject"
    APPROVAL_READ = "approval:read"
    
    ARTIFACT_READ = "artifact:read"
    ARTIFACT_WRITE = "artifact:write"
    
    ADMIN = "admin:*"


class Role:
    """Role with associated permissions."""
    
    def __init__(self, name: str, permissions: set[Permission]):
        self.name = name
        self.permissions = permissions
    
    def has_permission(self, permission: Permission) -> bool:
        """Check if role has permission."""
        # Admin has all permissions
        if Permission.ADMIN in self.permissions:
            return True
        # Check specific permission
        if permission in self.permissions:
            return True
        # Check wildcard
        wildcard = permission.split(":")[0] + ":*"
        if Permission(wildcard) in self.permissions:
            return True
        return False


# Predefined roles
ROLES = {
    "admin": Role("admin", {Permission.ADMIN}),
    
    "tech_lead": Role("tech_lead", {
        Permission.SESSION_CREATE,
        Permission.SESSION_READ,
        Permission.SESSION_UPDATE,
        Permission.STAGE_EXECUTE,
        Permission.STAGE_READ,
        Permission.APPROVAL_APPROVE,
        Permission.APPROVAL_REJECT,
        Permission.APPROVAL_READ,
        Permission.ARTIFACT_READ,
        Permission.ARTIFACT_WRITE,
    }),
    
    "developer": Role("developer", {
        Permission.SESSION_CREATE,
        Permission.SESSION_READ,
        Permission.SESSION_UPDATE,
        Permission.STAGE_EXECUTE,
        Permission.STAGE_READ,
        Permission.APPROVAL_READ,
        Permission.ARTIFACT_READ,
        Permission.ARTIFACT_WRITE,
    }),
    
    "viewer": Role("viewer", {
        Permission.SESSION_READ,
        Permission.STAGE_READ,
        Permission.APPROVAL_READ,
        Permission.ARTIFACT_READ,
    }),
}


class RBAC:
    """Role-Based Access Control manager."""
    
    def __init__(self):
        self._user_roles: dict[str, str] = {}  # user_id -> role_name
    
    def assign_role(self, user_id: str, role_name: str) -> None:
        """Assign role to user.
        
        Args:
            user_id: User identifier
            role_name: Role name
            
        Raises:
            ValueError: If role doesn't exist
        """
        if role_name not in ROLES:
            raise ValueError(f"Unknown role: {role_name}")
        self._user_roles[user_id] = role_name
    
    def get_user_role(self, user_id: str) -> Role | None:
        """Get user's role.
        
        Args:
            user_id: User identifier
            
        Returns:
            Role or None
        """
        role_name = self._user_roles.get(user_id)
        if role_name:
            return ROLES[role_name]
        return None
    
    def check_permission(self, user_id: str, permission: Permission) -> bool:
        """Check if user has permission.
        
        Args:
            user_id: User identifier
            permission: Permission to check
            
        Returns:
            True if user has permission
        """
        role = self.get_user_role(user_id)
        if not role:
            return False
        return role.has_permission(permission)
    
    def require_permission(self, permission: Permission):
        """Decorator to require permission.
        
        Usage:
            @rbac.require_permission(Permission.APPROVAL_APPROVE)
            async def approve_stage(...):
                ...
        """
        def decorator(func: Callable) -> Callable:
            @wraps(func)
            async def async_wrapper(*args, **kwargs):
                # Extract user_id from kwargs or args
                user_id = kwargs.get("user_id") or kwargs.get("approved_by") or kwargs.get("rejected_by")
                if not user_id:
                    raise PermissionError("User ID required")
                
                if not self.check_permission(user_id, permission):
                    raise PermissionError(
                        f"User {user_id} lacks permission {permission.value}"
                    )
                
                return await func(*args, **kwargs)
            
            @wraps(func)
            def sync_wrapper(*args, **kwargs):
                user_id = kwargs.get("user_id") or kwargs.get("approved_by") or kwargs.get("rejected_by")
                if not user_id:
                    raise PermissionError("User ID required")
                
                if not self.check_permission(user_id, permission):
                    raise PermissionError(
                        f"User {user_id} lacks permission {permission.value}"
                    )
                
                return func(*args, **kwargs)
            
            return async_wrapper if func.__code__.co_flags & 0x80 else sync_wrapper
        return decorator


# Global RBAC instance
_rbac = RBAC()


def get_rbac() -> RBAC:
    """Get global RBAC instance."""
    return _rbac
