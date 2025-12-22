"""Task manager for running scraper scripts from web interface."""

import os
import subprocess
import json
import threading
import signal
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
        self.processes = {}  # Store process objects for cancellation
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
        # Security: Whitelist of allowed scripts
        ALLOWED_SCRIPTS = {
            'run_scraper.py',
            'run_version_scraper.py',
            'run_downloader.py',
            'run_description_downloader.py',
            'run_index_search.py'
        }

        def run():
            with self.lock:
                self.tasks[task_id] = {
                    'status': 'running',
                    'started_at': datetime.now().isoformat(),
                    'script': script_name,
                    'progress': 0,
                    'message': 'Starting...',
                    'current_action': 'Initializing...'
                }
                self._save_status()

            try:
                # Security: Validate script_name is in whitelist
                if script_name not in ALLOWED_SCRIPTS:
                    error_msg = f"Script not allowed: {script_name}. Only whitelisted scripts can be executed."
                    logger.error(error_msg)
                    with self.lock:
                        self.tasks[task_id]['status'] = 'failed'
                        self.tasks[task_id]['message'] = error_msg
                        self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                        self.tasks[task_id]['error'] = error_msg
                        self._save_status()
                    return

                # Security: Validate script_name doesn't contain path traversal
                if '..' in script_name or '/' in script_name or '\\' in script_name:
                    error_msg = f"Invalid script name: {script_name}"
                    logger.error(error_msg)
                    with self.lock:
                        self.tasks[task_id]['status'] = 'failed'
                        self.tasks[task_id]['message'] = error_msg
                        self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                        self.tasks[task_id]['error'] = error_msg
                        self._save_status()
                    return

                # Get base directory
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                script_path = os.path.join(base_dir, script_name)
                
                # Try to use Python from venv, fallback to system Python
                python_exe = 'python'
                venv_python = os.path.join(base_dir, 'venv', 'Scripts', 'python.exe')
                if os.path.exists(venv_python):
                    python_exe = venv_python
                    logger.info(f"Using venv Python: {python_exe}")
                else:
                    logger.info(f"Using system Python: {python_exe}")
                
                # Verify script exists
                if not os.path.exists(script_path):
                    raise FileNotFoundError(f"Script not found: {script_path}")
                
                # Build command
                cmd = [python_exe, script_path]
                if args:
                    cmd.extend(args)
                
                logger.info(f"Starting task {task_id}: {' '.join(cmd)}")
                logger.info(f"Working directory: {base_dir}")
                
                # Prepare environment
                env = os.environ.copy()
                # Ensure Python path includes the project directory
                pythonpath = env.get('PYTHONPATH', '')
                if pythonpath:
                    env['PYTHONPATH'] = f"{base_dir};{pythonpath}" if os.name == 'nt' else f"{base_dir}:{pythonpath}"
                else:
                    env['PYTHONPATH'] = base_dir
                
                # Run process
                # Use UTF-8 encoding explicitly to avoid Windows charmap codec errors
                process = subprocess.Popen(
                    cmd,
                    cwd=base_dir,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,  # Combine stderr into stdout for easier reading
                    text=True,
                    encoding='utf-8',
                    errors='replace',  # Replace invalid characters instead of failing
                    bufsize=1,
                    env=env,
                    shell=False
                )
                
                # Update status and store process
                with self.lock:
                    self.tasks[task_id]['pid'] = process.pid
                    self.tasks[task_id]['message'] = 'Running...'
                    self.tasks[task_id]['current_action'] = 'Initializing...'
                    self.processes[task_id] = process  # Store process for cancellation
                    self._save_status()
                
                # Wait for completion
                stdout, _ = process.communicate()  # stderr is combined with stdout
                
                # Extract current action from output
                if stdout:
                    stdout_lines = stdout.split('\n')
                    current_action = 'Running...'
                    # Look for meaningful lines in output
                    for line in reversed(stdout_lines[-20:]):  # Check last 20 lines
                        line_stripped = line.strip()
                        if line_stripped:
                            line_lower = line_stripped.lower()
                            # Update current action based on output
                            if any(keyword in line_lower for keyword in ['scraping', 'scrape', 'downloading', 'download', 
                                                                          'processing', 'process', 'saving', 'save', 
                                                                          'fetching', 'fetch']):
                                current_action = line_stripped[:100] if len(line_stripped) > 100 else line_stripped
                                break
                    
                    # Update current action before final status
                    with self.lock:
                        self.tasks[task_id]['current_action'] = current_action
                        self._save_status()
                
                # Update final status
                with self.lock:
                    if process.returncode == 0:
                        self.tasks[task_id]['status'] = 'completed'
                        self.tasks[task_id]['message'] = 'Completed successfully'
                    else:
                        self.tasks[task_id]['status'] = 'failed'
                        self.tasks[task_id]['message'] = f'Failed with code {process.returncode}'
                        
                        # Save full output (last 3000 chars) - includes both stdout and stderr
                        error_output = ""
                        if stdout:
                            error_output = stdout[-3000:] if len(stdout) > 3000 else stdout
                        
                        if error_output:
                            self.tasks[task_id]['error'] = error_output
                            # Try to extract key error message
                            error_lines = error_output.split('\n')
                            for line in reversed(error_lines):
                                line_stripped = line.strip()
                                if line_stripped and (
                                    'error' in line_stripped.lower() or 
                                    '❌' in line_stripped or 
                                    'failed' in line_stripped.lower() or
                                    'exception' in line_stripped.lower() or
                                    'traceback' in line_stripped.lower()
                                ):
                                    # Extract meaningful error message
                                    if len(line_stripped) > 200:
                                        self.tasks[task_id]['message'] = line_stripped[:197] + '...'
                                    else:
                                        self.tasks[task_id]['message'] = line_stripped
                                    break
                    
                    # Save full output for debugging (last 2000 chars)
                    if stdout:
                        self.tasks[task_id]['output'] = stdout[-2000:] if len(stdout) > 2000 else stdout
                    
                    self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                    self.tasks[task_id]['return_code'] = process.returncode
                    self.tasks[task_id]['progress'] = 100
                    self._save_status()
                
                logger.info(f"Task {task_id} finished with code {process.returncode}")
                if process.returncode != 0:
                    error_preview = stdout[-500:] if stdout and len(stdout) > 500 else (stdout if stdout else 'No output')
                    logger.error(f"Task {task_id} error output: {error_preview}")
                
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

    def start_download_descriptions(self, addon_key: Optional[str] = None, download_media: bool = True) -> str:
        """Start description download task."""
        task_id = f"download_descriptions_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        args = []
        if addon_key:
            args.extend(['--addon-key', addon_key])
        if not download_media:
            args.append('--no-media')
        self._run_task(task_id, 'run_description_downloader.py', args)
        return task_id
    
    def start_build_search_index(self) -> str:
        """Start search index building task."""
        task_id = f"build_index_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self._run_task(task_id, 'run_index_search.py')
        return task_id

    def start_full_pipeline(
        self,
        resume_scrape: bool = False,
        download_product: Optional[str] = None,
        download_media: bool = True
    ) -> str:
        """
        Start all tasks sequentially: scrape apps → scrape versions → download binaries → download descriptions.
        
        Args:
            resume_scrape: Resume app scraping from checkpoint
            download_product: Optional product filter for binary download
            download_media: Download media files for descriptions
            
        Returns:
            Pipeline task ID
        """
        import time
        
        pipeline_id = f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        def run_pipeline():
            """Run all tasks sequentially."""
            steps = []
            
            try:
                # Step 1: Scrape Apps
                logger.info(f"[Pipeline {pipeline_id}] Starting step 1: Scrape Apps")
                with self.lock:
                    self.tasks[pipeline_id] = {
                        'status': 'running',
                        'started_at': datetime.now().isoformat(),
                        'script': 'pipeline',
                        'progress': 0,
                        'message': 'Step 1/4: Scraping apps...',
                        'current_step': 1,
                        'total_steps': 4,
                        'steps': []
                    }
                    self._save_status()
                
                task_id_1 = self.start_scrape_apps(resume=resume_scrape)
                steps.append({'name': 'Scrape Apps', 'task_id': task_id_1, 'status': 'running'})
                
                # Wait for completion
                while True:
                    time.sleep(5)
                    status = self.get_task_status(task_id_1)
                    if not status:
                        break
                    if status.get('status') in ['completed', 'failed']:
                        steps[-1]['status'] = status.get('status')
                        if status.get('status') == 'failed':
                            raise Exception(f"Step 1 (Scrape Apps) failed: {status.get('message', 'Unknown error')}")
                        break
                
                # Step 2: Scrape Versions
                logger.info(f"[Pipeline {pipeline_id}] Starting step 2: Scrape Versions")
                with self.lock:
                    self.tasks[pipeline_id]['progress'] = 25
                    self.tasks[pipeline_id]['message'] = 'Step 2/4: Scraping versions...'
                    self.tasks[pipeline_id]['current_step'] = 2
                    self._save_status()
                
                task_id_2 = self.start_scrape_versions()
                steps.append({'name': 'Scrape Versions', 'task_id': task_id_2, 'status': 'running'})
                
                # Wait for completion
                while True:
                    time.sleep(5)
                    status = self.get_task_status(task_id_2)
                    if not status:
                        break
                    if status.get('status') in ['completed', 'failed']:
                        steps[-1]['status'] = status.get('status')
                        if status.get('status') == 'failed':
                            raise Exception(f"Step 2 (Scrape Versions) failed: {status.get('message', 'Unknown error')}")
                        break
                
                # Step 3: Download Binaries
                logger.info(f"[Pipeline {pipeline_id}] Starting step 3: Download Binaries")
                with self.lock:
                    self.tasks[pipeline_id]['progress'] = 50
                    self.tasks[pipeline_id]['message'] = 'Step 3/4: Downloading binaries...'
                    self.tasks[pipeline_id]['current_step'] = 3
                    self._save_status()
                
                task_id_3 = self.start_download_binaries(product=download_product)
                steps.append({'name': 'Download Binaries', 'task_id': task_id_3, 'status': 'running'})
                
                # Wait for completion
                while True:
                    time.sleep(5)
                    status = self.get_task_status(task_id_3)
                    if not status:
                        break
                    if status.get('status') in ['completed', 'failed']:
                        steps[-1]['status'] = status.get('status')
                        if status.get('status') == 'failed':
                            raise Exception(f"Step 3 (Download Binaries) failed: {status.get('message', 'Unknown error')}")
                        break
                
                # Step 4: Download Descriptions
                logger.info(f"[Pipeline {pipeline_id}] Starting step 4: Download Descriptions")
                with self.lock:
                    self.tasks[pipeline_id]['progress'] = 75
                    self.tasks[pipeline_id]['message'] = 'Step 4/4: Downloading descriptions...'
                    self.tasks[pipeline_id]['current_step'] = 4
                    self._save_status()
                
                task_id_4 = self.start_download_descriptions(download_media=download_media)
                steps.append({'name': 'Download Descriptions', 'task_id': task_id_4, 'status': 'running'})
                
                # Wait for completion
                while True:
                    time.sleep(5)
                    status = self.get_task_status(task_id_4)
                    if not status:
                        break
                    if status.get('status') in ['completed', 'failed']:
                        steps[-1]['status'] = status.get('status')
                        if status.get('status') == 'failed':
                            raise Exception(f"Step 4 (Download Descriptions) failed: {status.get('message', 'Unknown error')}")
                        break
                
                # All steps completed
                with self.lock:
                    self.tasks[pipeline_id]['status'] = 'completed'
                    self.tasks[pipeline_id]['progress'] = 100
                    self.tasks[pipeline_id]['message'] = 'All steps completed successfully!'
                    self.tasks[pipeline_id]['finished_at'] = datetime.now().isoformat()
                    self.tasks[pipeline_id]['steps'] = steps
                    self._save_status()
                
                logger.info(f"[Pipeline {pipeline_id}] All steps completed successfully")
                
            except Exception as e:
                with self.lock:
                    self.tasks[pipeline_id]['status'] = 'failed'
                    self.tasks[pipeline_id]['message'] = f'Pipeline failed: {str(e)}'
                    self.tasks[pipeline_id]['finished_at'] = datetime.now().isoformat()
                    self.tasks[pipeline_id]['steps'] = steps
                    self.tasks[pipeline_id]['error'] = str(e)
                    self._save_status()
                logger.error(f"[Pipeline {pipeline_id}] Failed: {str(e)}")
        
        # Run pipeline in background thread
        thread = threading.Thread(target=run_pipeline, daemon=True)
        thread.start()
        
        return pipeline_id
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Get status of a task."""
        with self.lock:
            return self.tasks.get(task_id)
    
    def get_all_tasks(self) -> Dict:
        """Get all tasks."""
        with self.lock:
            return self.tasks.copy()
    
    def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task.
        
        Args:
            task_id: Task ID to cancel
            
        Returns:
            True if task was cancelled, False otherwise
        """
        with self.lock:
            if task_id not in self.tasks:
                logger.warning(f"Task {task_id} not found for cancellation")
                return False
            
            task = self.tasks[task_id]
            current_status = task.get('status')
            
            # Check if task is running
            if current_status != 'running':
                # If task is already completed/failed/cancelled, we can't cancel it
                if current_status in ['completed', 'failed', 'cancelled']:
                    logger.warning(f"Task {task_id} is already {current_status}, cannot cancel")
                    return False
                # For other statuses (e.g., 'pending'), mark as cancelled anyway
                logger.info(f"Task {task_id} is not running (status: {current_status}), marking as cancelled")
                self.tasks[task_id]['status'] = 'cancelled'
                self.tasks[task_id]['message'] = f'Cancelled by user (was {current_status})'
                self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                self._save_status()
                return True
            
            # Try to get process object
            process = self.processes.get(task_id)
            
            if process:
                try:
                    # Terminate the process
                    if os.name == 'nt':  # Windows
                        # On Windows, use terminate() which sends SIGTERM
                        process.terminate()
                        # Wait a bit, then force kill if needed
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            logger.info(f"Force killed task {task_id}")
                    else:  # Unix-like
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            logger.info(f"Force killed task {task_id}")
                    
                    # Update task status
                    self.tasks[task_id]['status'] = 'cancelled'
                    self.tasks[task_id]['message'] = 'Cancelled by user'
                    self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                    self.tasks[task_id]['return_code'] = -1
                    
                    # Remove process from storage
                    del self.processes[task_id]
                    
                    self._save_status()
                    logger.info(f"Task {task_id} cancelled successfully")
                    return True
                    
                except Exception as e:
                    logger.error(f"Error cancelling task {task_id}: {str(e)}")
                    # Try to kill by PID as fallback
                    pid = task.get('pid')
                    if pid:
                        try:
                            if os.name == 'nt':  # Windows
                                os.kill(pid, signal.SIGTERM)
                            else:
                                os.kill(pid, signal.SIGTERM)
                            
                            self.tasks[task_id]['status'] = 'cancelled'
                            self.tasks[task_id]['message'] = 'Cancelled by user (via PID)'
                            self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                            self.tasks[task_id]['return_code'] = -1
                            
                            if task_id in self.processes:
                                del self.processes[task_id]
                            
                            self._save_status()
                            logger.info(f"Task {task_id} cancelled via PID")
                            return True
                        except Exception as pid_error:
                            logger.error(f"Failed to cancel task {task_id} via PID: {str(pid_error)}")
                            return False
                    return False
            else:
                # Process object not available, try by PID
                pid = task.get('pid')
                if pid:
                    try:
                        # Check if process is still running (Windows)
                        if os.name == 'nt':  # Windows
                            try:
                                # Signal 0 doesn't kill, just checks if process exists
                                os.kill(pid, 0)
                            except ProcessLookupError:
                                # Process already finished
                                logger.warning(f"Task {task_id} process (PID {pid}) already finished")
                                self.tasks[task_id]['status'] = 'cancelled'
                                self.tasks[task_id]['message'] = 'Cancelled by user (process already finished)'
                                self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                                self._save_status()
                                return True
                            except PermissionError:
                                # Process exists but we don't have permission
                                logger.warning(f"Task {task_id} process (PID {pid}) exists but no permission to kill")
                                # Mark as cancelled anyway
                                self.tasks[task_id]['status'] = 'cancelled'
                                self.tasks[task_id]['message'] = 'Cancelled by user (marked as cancelled)'
                                self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                                self._save_status()
                                return True
                            
                            # Process exists, try to terminate it
                            os.kill(pid, signal.SIGTERM)
                        else:  # Unix-like
                            os.kill(pid, signal.SIGTERM)
                        
                        self.tasks[task_id]['status'] = 'cancelled'
                        self.tasks[task_id]['message'] = 'Cancelled by user (via PID)'
                        self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                        self.tasks[task_id]['return_code'] = -1
                        
                        if task_id in self.processes:
                            del self.processes[task_id]
                        
                        self._save_status()
                        logger.info(f"Task {task_id} cancelled via PID")
                        return True
                    except ProcessLookupError:
                        # Process already finished
                        logger.warning(f"Task {task_id} process (PID {pid}) already finished")
                        self.tasks[task_id]['status'] = 'cancelled'
                        self.tasks[task_id]['message'] = 'Cancelled by user (process already finished)'
                        self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                        self._save_status()
                        return True
                    except Exception as e:
                        logger.error(f"Failed to cancel task {task_id} via PID: {str(e)}")
                        # Even if we can't kill the process, mark task as cancelled
                        # This handles cases where process is already dead or we lost track of it
                        self.tasks[task_id]['status'] = 'cancelled'
                        self.tasks[task_id]['message'] = f'Cancelled by user (marked as cancelled, error: {str(e)})'
                        self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                        self._save_status()
                        logger.info(f"Task {task_id} marked as cancelled despite error")
                        return True
                else:
                    # No PID available, but task is marked as running
                    # This can happen if task was loaded from file but process was lost
                    logger.warning(f"Task {task_id} has no process object or PID, but status is 'running'. Marking as cancelled.")
                    self.tasks[task_id]['status'] = 'cancelled'
                    self.tasks[task_id]['message'] = 'Cancelled by user (process not found, likely already finished)'
                    self.tasks[task_id]['finished_at'] = datetime.now().isoformat()
                    self._save_status()
                    return True
    
    def get_latest_task(self, task_type: str) -> Optional[Dict]:
        """Get latest task of specific type."""
        with self.lock:
            matching = {k: v for k, v in self.tasks.items() if k.startswith(task_type)}
            if not matching:
                return None
            # Sort by started_at and return latest
            latest = max(matching.items(), key=lambda x: x[1].get('started_at', ''))
            return latest[1]
    
    def clear_completed_tasks(self) -> int:
        """
        Clear all completed, failed, and cancelled tasks.
        
        Returns:
            Number of tasks cleared
        """
        with self.lock:
            to_remove = []
            for task_id, task in self.tasks.items():
                status = task.get('status', '')
                if status in ['completed', 'failed', 'cancelled']:
                    to_remove.append(task_id)
            
            for task_id in to_remove:
                del self.tasks[task_id]
                # Also remove from processes if exists
                if task_id in self.processes:
                    del self.processes[task_id]
            
            self._save_status()
            logger.info(f"Cleared {len(to_remove)} completed/failed/cancelled tasks")
            return len(to_remove)
    
    def get_task_log_file(self, task_id: str) -> Optional[str]:
        """
        Get log file path for a task based on script name.
        
        Args:
            task_id: Task ID
            
        Returns:
            Path to log file or None
        """
        task = self.tasks.get(task_id)
        if not task:
            return None
        
        script = task.get('script', '')
        
        # For pipeline tasks, check the current step to determine which log to use
        if script == 'pipeline':
            current_step = task.get('current_step', 0)
            # Pipeline steps:
            # 1 = Scrape Apps -> scraper.log
            # 2 = Scrape Versions -> scraper.log
            # 3 = Download Binaries -> download.log
            # 4 = Download Descriptions -> description_downloader.log
            if current_step in [1, 2]:
                return os.path.join(settings.LOGS_DIR, 'scraper.log')
            elif current_step == 3:
                return os.path.join(settings.LOGS_DIR, 'download.log')
            elif current_step == 4:
                return os.path.join(settings.LOGS_DIR, 'description_downloader.log')
            else:
                # Default to scraper.log for pipeline if step is unknown
                return os.path.join(settings.LOGS_DIR, 'scraper.log')
        
        log_file_map = {
            'run_scraper.py': 'scraper.log',
            'run_version_scraper.py': 'scraper.log',
            'run_downloader.py': 'download.log',
            'run_description_downloader.py': 'description_downloader.log'
        }
        
        log_filename = log_file_map.get(script)
        if log_filename:
            return os.path.join(settings.LOGS_DIR, log_filename)
        return None


# Global task manager instance
_task_manager = None

def get_task_manager() -> TaskManager:
    """Get global task manager instance."""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager

