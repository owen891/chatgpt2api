from __future__ import annotations

import time
import unittest
from threading import BoundedSemaphore, Lock, Thread

from services.account_service import AccountService


class ReloginConcurrencyTests(unittest.TestCase):
    def test_relogin_jobs_are_bounded_and_release_tokens(self) -> None:
        service = AccountService.__new__(AccountService)
        service._relogin_progress_lock = Lock()
        service._relogin_active_tokens = set()
        service._relogin_semaphore = BoundedSemaphore(AccountService._RELOGIN_MAX_CONCURRENCY)
        active = 0
        max_active = 0
        state_lock = Lock()

        def fake_relogin(_token, _email, _password, _event, _progress_id=None):
            nonlocal active, max_active
            with state_lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01)
            with state_lock:
                active -= 1

        service._password_re_login_thread = fake_relogin
        jobs = [(f"token-{index}", "user@example.com", "password", "test") for index in range(8)]
        service._relogin_active_tokens.update(job[0] for job in jobs)

        workers = [
            Thread(target=service._run_password_relogin_jobs, args=(jobs[:4],)),
            Thread(target=service._run_password_relogin_jobs, args=(jobs[4:],)),
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self.assertLessEqual(max_active, AccountService._RELOGIN_MAX_CONCURRENCY)
        self.assertEqual(service._relogin_active_tokens, set())


if __name__ == "__main__":
    unittest.main()
