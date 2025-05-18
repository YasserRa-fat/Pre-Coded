import threading
import logging
import traceback
from typing import Optional, Any

logger = logging.getLogger(__name__)

class ProjectContextLocal(threading.local):
    """
    Thread-local storage for project context.
    Handles project ID, database alias, and request context.
    """
    def __init__(self):
        self._project_id: Optional[int] = None
        self._db_alias: Optional[str] = None
        self._request = None
        self._context: dict = {}
        self._initialized = True
        
    @property
    def project_id(self) -> Optional[int]:
        return self._project_id
        
    @project_id.setter
    def project_id(self, value: Optional[int]):
        if value is not None and not isinstance(value, int):
            try:
                value = int(value)
            except (TypeError, ValueError):
                logger.error(f"Invalid project_id value: {value}")
                return
        self._project_id = value
        logger.debug(f"Set thread_local.project_id to {value}")
        
    @property
    def db_alias(self) -> Optional[str]:
        if self._db_alias:
            return self._db_alias
        if self._project_id:
            return f"project_{self._project_id}"
        return None
        
    @db_alias.setter
    def db_alias(self, value: Optional[str]):
        self._db_alias = value
        logger.debug(f"Set thread_local.db_alias to {value}")
        
    @property
    def request(self):
        return self._request
        
    @request.setter
    def request(self, value):
        self._request = value
        if value is not None:
            # Try to extract project context from request
            try:
                project_db_alias = getattr(value, 'project_db_alias', None)
                if project_db_alias and project_db_alias != 'default':
                    project_id = int(project_db_alias.split('_')[1])
                    self.project_id = project_id
                    self._db_alias = project_db_alias
                    logger.debug(f"Extracted project_id={project_id} from request")
            except Exception as e:
                logger.error(f"Error extracting project context from request: {str(e)}")
                
    def set_context(self, key: str, value: Any):
        """Set a value in the context dictionary"""
        self._context[key] = value
        logger.debug(f"Set thread_local context: {key}={value.__class__.__name__}")
        
    def get_context(self, key: str, default: Any = None) -> Any:
        """Get a value from the context dictionary"""
        value = self._context.get(key, default)
        if value is None and key == 'project' and self._project_id:
            # Special case for project: try to get it from project_id if not in context
            try:
                from create_api.utils import get_current_project
                project = get_current_project(project_id=self._project_id)
                if project:
                    self.set_context('project', project)
                    return project
            except Exception as e:
                logger.debug(f"Failed to get project for context from project_id={self._project_id}: {str(e)}")
        return value
        
    def clear(self):
        """Clear all thread-local data"""
        if not hasattr(self, '_initialized'):
            return  # Avoid clearing before initialization
            
        try:
            self._project_id = None
            self._db_alias = None
            self._request = None
            self._context.clear()
            logger.debug(f"Cleared thread_local context. Stack: {traceback.format_stack()[-5:-1]}")
        except Exception as e:
            logger.error(f"Error clearing thread local: {str(e)}")

# Global thread-local instance
thread_local = ProjectContextLocal()