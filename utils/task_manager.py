"""Task manager for running scraper scripts from web interface."""

import os
import subprocess
import json
import threading
from datetime import datetime
from typing import Dict, Optional
from config import settings
from utils.logger import get_logger

logger = get_logger('task_manager')

# Task status file
TASK_STATUS_FILE = os.path.join(settings.METADATA_DIR, 'task_status.json')


class TaskManager:
    """Manages background tasks for scraper operations."""
    
    def __init__(self):
        """Initialize task manager."""
        self.tasks = {}
        self.lock = threading.Lock()
        self._load_status()
    
    def _load_status(self):
        """Load task status from file."""
        if os.path.exists(TASK_STATUS_FILE):
            try:
                with open(TASK_STATUS_FILE, 'r', encoding='utf-8') as f:
                    self.tasks = json.load(f)
            except Exception as e:
                logger.error(f"Error loading task status: {str(e)}")
                self.tasks = {}
    
    def _save_status(self):
        """Save task status to file."""
        try:
            os.makedirs(os.path.dirname(TASK_STATUS_FILE), exist_ok=True)
            with open(TASK_STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.tasks, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Error saving task status: {str(e)}")
    
    def _run_task(self, task_id: str, script_name: str, args: list = None):
        """Run a task in background thread."""
        def run():
            with self.lock:
                self.tasks[task_id] = {
                    'status': 'running',
                    'started_at': datetime.now().isoformat(),
                    'script': script_name,
                    'progress': 0,
                    'message': 'Starting...'
                }
                self._save_status()
            
            try:
                # Get base directory
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                script_path = os.path.join(base_dir, script_name)
                
                # Try to use Python from venv, fallback to system Python
                python_exe = 'python'
                venv_python = os.path.join(base_dir, 'venv', 'Scripts', 'python.exe')
                if os.path.exists(venv_python):
                    python_exe = venv_python
                
                # Build command
                cmd = [python_exe, script_path]
                if args:
                    cmd.extend(args)
                
                logger.info(f"Starting task {task_id}: {' '.join(cmd)}")
                
                # Run process
                process = subprocess.Popen(
                    cmd,
                    cwd=base_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1
                )
                
                # Update status
                with self.lock:
                    self.tasks[task_id]['pid'] = process.pid
                    self.tasks[task_id]['message'] = 'Running...'
                    self._save_status()
                
                # Wait for completion
                stdout, stderr = process.communicate()
                
                # Update final status
                with self.lock:
                    if process.returncode == 0:
                        self.tasks[task_id]['status'] = 'completed'
                        self.tasks[task_id]['message'] = 'Completed successfully'
                    else:
                        self.tasks[task_id]['status'] = 'failed'
                        self.tasks[task_id]['message'] = f'Failed with code {process.returncode}'
                        if stderr:
                            self.tasks[task_id]['error'] = stderr[:500]  # Limit error message
                    
                    self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                    self.tasks[task_id]['return_code'] = process.returncode
                    self.tasks[task_id]['progress'] = 100
                    self._save_status()
                
                logger.info(f"Task {task_id} finished with code {process.returncode}")
                
            except Exception as e:
                with self.lock:
                    self.tasks[task_id]['status'] = 'failed'
                    self.tasks[task_id]['message'] = f'Error: {str(e)}'
                    self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                    self.tasks[task_id]['error'] = str(e)
                    self._save_status()
                logger.error(f"Task {task_id} error: {str(e)}")
        
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread
    
    def start_scrape_apps(self, resume: bool = False) -> str:
        """Start app scraping task."""
        task_id = f"scrape_apps_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        args = ['--resume'] if resume else []
        self._run_task(task_id, 'run_scraper.py', args)
        return task_id
    
    def start_scrape_versions(self) -> str:
        """Start version scraping task."""
        task_id = f"scrape_versions_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._run_task(task_id, 'run_version_scraper.py')
        return task_id
    
    def start_download_binaries(self, product: Optional[str] = None) -> str:
        """Start binary download task."""
        task_id = f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        args = [product] if product else []
        self._run_task(task_id, 'run_downloader.py', args)
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Get status of a task."""
        with self.lock:
            return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> Dict:
        """Get all tasks."""
        with self.lock:
            return self.tasks.copy()
    
    def get_latest_task(self, task_type: str) -> Optional[Dict]:
        """Get latest task of specific type."""
        with self.lock:
            matching = {k: v for k, v in self.tasks.items() if k.startswith(task_type)}
            if not matching:
                return None
            # Sort by started_at and return latest
            latest = max(matching.items(), key=lambda x: x[1].get('started_at', ''))
            return latest[1]


# Global task manager instance
_task_manager = None

def get_task_manager() -> TaskManager:
    """Get global task manager instance."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager

