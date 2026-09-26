import os
import logging
import subprocess

logger = logging.getLogger(__name__)


class DeepSeekBrowserAgent:
    """
    Pure Transport Driver for DeepSeek Browser CLI (dsa --headless).
    Responsible ONLY for sending raw prompt text and returning raw output text.
    """
    
    def __init__(self, session_id: int = 1):
        if not isinstance(session_id, int):
            raise TypeError(f"FAIL-FAST: session_id must be an int, got {type(session_id)}")
        if not (1 <= session_id <= 7):
            raise ValueError(f"FAIL-FAST: session_id must be between 1 and 7, got {session_id}")
            
        self.session_id = session_id
        self.session_dir = f"C:\\Users\\BUSOLOVE\\.deepseek-agent\\session_{self.session_id}"

    def send_prompt(self, full_prompt_text: str) -> str:
        """
        Sends assembled prompt text to DeepSeek CLI and returns raw response string.
        """
        if not isinstance(full_prompt_text, str) or not full_prompt_text.strip():
            raise ValueError("FAIL-FAST: full_prompt_text must be a non-empty string.")

        env = os.environ.copy()
        env["DS_SESSION_DIR"] = self.session_dir
        cmd = ["dsa", "--headless", full_prompt_text]

        logger.info(f"[DeepSeek Transport] Dispatching prompt on Session {self.session_id}...")
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            err_msg = result.stderr.strip() or result.stdout.strip()
            logger.error(f"[DeepSeek Transport] Failed with code {result.returncode}: {err_msg}")
            raise RuntimeError(f"FAIL-FAST: DeepSeek CLI failed with code {result.returncode}: {err_msg}")

        return result.stdout.strip()
