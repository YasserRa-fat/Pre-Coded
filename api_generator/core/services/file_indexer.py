# core/services/file_indexer.py
import threading
from collections import defaultdict
from django.apps import apps
from create_api.models import (
    TemplateFile, ModelFile, ViewFile, FormFile,
    AppFile, ProjectFile, StaticFile
)
import logging
from pathlib import Path
import re
import os

logger = logging.getLogger(__name__)

class FileIndexer:
    """
    Dynamic file indexer that maintains project-specific indexes:
      - mapping app_name → list of files
      - mapping keywords → list of file paths 
      - mapping canonical paths → file instances
    """
    _lock = threading.Lock()
    _loaded_projects = set()  # Track which projects are loaded
    _indexes = {}  # Project-specific indexes

    @classmethod
    def _get_project_index(cls, project_id):
        """Get or create project-specific index"""
        if project_id not in cls._indexes:
            logger.debug(f"Creating new index for project {project_id}")
            cls._indexes[project_id] = {
                'app_to_files': defaultdict(list),
                'path_to_instance': {},
                'path_aliases': defaultdict(set)  # Track path variations
            }
        return cls._indexes[project_id]

    @classmethod
    def _normalize_path(cls, path):
        """
        Normalize path to canonical form - handling both forward and backslashes.
        
        This is critical for AI interactions, where paths might be provided with
        different separators depending on the source.
        """
        if not path:
            logger.debug("Empty path provided to normalize_path")
            return ''
            
        # Log original path
        logger.debug(f"Normalizing path: '{path}'")
            
        # First convert to a clean path with forward slashes
        path = str(path).strip()
        path = path.replace('\\', '/')
        
        # Remove any leading/trailing slashes
        path = path.strip('/')
        
        # Generate alternative representation for indexing
        alt_path = path.replace('/', '\\')
        
        # Log both representations for debugging
        # logger.debug(f"Normalized path: '{path}' (alt: '{alt_path}')")
        
        return path

    @classmethod
    def _get_path_variations(cls, path):
        """Generate possible path variations with improved template handling"""
        path = cls._normalize_path(path)
        logger.debug(f"Generating variations for path: '{path}'")
        
        variations = {path, path.replace('/', '\\')}
        
        # Handle template paths specifically
        if path.startswith('templates/'):
            # Add version without templates/ prefix
            no_prefix = path[len('templates/'):]
            variations.add(no_prefix)
            variations.add(no_prefix.replace('/', '\\'))
            logger.debug(f"Added template variations: {no_prefix}")
        else:
            # Add version with templates/ prefix
            with_prefix = f"templates/{path}"
            variations.add(with_prefix)
            variations.add(with_prefix.replace('/', '\\'))
            logger.debug(f"Added template variations: {with_prefix}")
        
        # Add variation without app prefix
        parts = path.split('/')
        if len(parts) > 1:
            variations.add(parts[-1])
            variations.add('/'.join(parts[1:]))
            variations.add('\\'.join(parts[1:]))
            logger.debug(f"Added path parts variations: {parts[-1]}, {'/'.join(parts[1:])}")
        
        logger.debug(f"Generated variations: {variations}")
        return variations

    @classmethod
    def load_index(cls, project_id):
        """Load or reload index for specific project"""
        with cls._lock:
            if project_id in cls._loaded_projects:
                logger.debug(f"Project {project_id} already loaded")
                return
                
            logger.info(f"Loading file index for project {project_id}")
            index = cls._get_project_index(project_id)
            
            # Clear existing project data
            index['app_to_files'].clear()
            index['path_to_instance'].clear()
            index['path_aliases'].clear()
            
            # Index all file types
            for model in (TemplateFile, ModelFile, ViewFile, FormFile, AppFile, ProjectFile, StaticFile):
                logger.debug(f"Indexing {model.__name__} files")
                # Always use the default DB for create_api models
                qs = model.objects.using('default').filter(project_id=project_id)
                for f in qs:
                    # Get base path and normalize
                    base_path = cls._normalize_path(f.path)
                    
                    # Get app name if available, always from default DB
                    app_name = None
                    if hasattr(f, 'app_id') and f.app_id:
                        from create_api.models import App
                        try:
                            app_obj = App.objects.using('default').get(id=f.app_id)
                            app_name = app_obj.name
                        except Exception:
                            app_name = None
                    
                    # Generate canonical path based on file type
                    if model.__name__ == 'TemplateFile' and not base_path.startswith('templates/'):
                        canonical_path = f"templates/{base_path}"
                    elif model.__name__ == 'StaticFile' and not base_path.startswith('static/'):
                        canonical_path = f"static/{base_path}"
                    elif model.__name__ == 'AppFile' and app_name and not base_path.startswith(f"apps/{app_name}/"):
                        canonical_path = f"apps/{app_name}/{base_path}"
                    elif model.__name__ in ('ModelFile', 'ViewFile', 'FormFile') and app_name and not base_path.startswith(f"{app_name}/"):
                        canonical_path = f"{app_name}/{base_path}"
                    else:
                        canonical_path = base_path

                    canonical_path = cls._normalize_path(canonical_path)
                    logger.debug(f"{model.__name__}: {f.path} -> {canonical_path}")

                    # Store canonical path and instance
                    index['path_to_instance'][canonical_path] = f
                    
                    # Also store Windows-style path for compatibility
                    win_path = canonical_path.replace('/', '\\')
                    index['path_to_instance'][win_path] = f
                    
                    # Store in app_to_files
                    app_key = app_name if app_name else None
                    if canonical_path not in index['app_to_files'][app_key]:
                        index['app_to_files'][app_key].append(canonical_path)
                    
                    # Generate and store path variations
                    variations = cls._get_path_variations(canonical_path)
                    index['path_aliases'][canonical_path].update(variations)
                    
                    # Also index original path if different
                    if canonical_path != f.path:
                        orig_variations = cls._get_path_variations(f.path)
                        index['path_aliases'][canonical_path].update(orig_variations)
            
            logger.info(f"Indexed {len(index['path_to_instance']) // 2} files for project {project_id}")  # Divide by 2 because we store both slash formats
            logger.debug(f"Canonical paths: {list(index['path_to_instance'].keys())}")
            cls._loaded_projects.add(project_id)

    @classmethod
    def get_candidates(cls, project_id, app_name=None):
        """Get candidate files, optionally filtered by app"""
        cls.load_index(project_id)
        index = cls._get_project_index(project_id)
        
        if app_name:
            paths = index['app_to_files'].get(app_name, [])
            logger.debug(f"Candidates for app {app_name}: {paths}")
            return paths
            
        # Return unique canonical paths (filtering out Windows duplicates)
        paths = []
        seen = set()
        for path in index['path_to_instance'].keys():
            norm_path = cls._normalize_path(path)
            if norm_path not in seen:
                seen.add(norm_path)
                paths.append(norm_path)
        
        logger.debug(f"All candidates: {paths}")
        return paths

    @classmethod
    def find_file(cls, project_id, path):
        """Find file by path, with improved template handling"""
        cls.load_index(project_id)
        index = cls._get_project_index(project_id)
        
        # Log the search attempt
        logger.info(f"Searching for file: '{path}' in project {project_id}")
        
        # Normalize the search path
        search_path = cls._normalize_path(path)
        # logger.debug(f"Normalized search path: '{search_path}'")
        
        # First try direct lookup with normalized path
        if search_path in index['path_to_instance']:
            logger.info(f"Found exact match for '{search_path}'")
            return index['path_to_instance'][search_path]
            
        # Try with templates/ prefix if not already present
        if not search_path.startswith('templates/'):
            template_path = f"templates/{search_path}"
            template_path = cls._normalize_path(template_path)
            logger.debug(f"Trying template path: '{template_path}'")
            if template_path in index['path_to_instance']:
                logger.info(f"Found template match for '{template_path}'")
                return index['path_to_instance'][template_path]
                
        # Try all path variations
        variations = cls._get_path_variations(search_path)
        logger.debug(f"Trying path variations: {variations}")
        for var in variations:
            if var in index['path_to_instance']:
                logger.info(f"Found variation match: '{var}'")
                return index['path_to_instance'][var]
                
        # Try fuzzy matching as last resort
        logger.debug("No exact matches found, trying fuzzy matching")
        best_match = None
        best_ratio = 0
        
        for canonical_path, variations in index['path_aliases'].items():
            # Check both the canonical path and its variations
            paths_to_check = {canonical_path} | variations
            for check_path in paths_to_check:
                ratio = cls._similarity_ratio(search_path, check_path)
                if ratio > best_ratio and ratio > 0.8:  # 80% similarity threshold
                    best_ratio = ratio
                    best_match = canonical_path
                    
        if best_match:
            logger.info(f"Found fuzzy match: '{best_match}' (similarity: {best_ratio:.2f})")
            return index['path_to_instance'][best_match]
            
        logger.warning(f"No matching file found for '{path}'")
        return None

    @classmethod
    def _similarity_ratio(cls, s1, s2):
        """Calculate similarity ratio between two strings"""
        import difflib
        return difflib.SequenceMatcher(None, s1, s2).ratio()

    @classmethod
    def get_content(cls, project_id, path):
        """Get file content by path"""
        file_obj = cls.find_file(project_id, path)
        if file_obj:
            return file_obj.content
        return ""

    @classmethod
    def reload_project(cls, project_id):
        """Force reload project index"""
        with cls._lock:
            if project_id in cls._loaded_projects:
                cls._loaded_projects.remove(project_id)
            if project_id in cls._indexes:
                del cls._indexes[project_id]
            cls.load_index(project_id)
