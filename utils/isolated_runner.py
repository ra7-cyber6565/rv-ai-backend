"""Trusted standalone container entrypoint. Never run user code on the host."""
import base64
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import time


def main():
    runtime, entrypoint = sys.argv[1:3]
    command = (["python3", "-B", "/inputs/"+entrypoint] if runtime == "python"
               else ["node", "/inputs/"+entrypoint])
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8"},
        start_new_session=True)
    output, failure, end = bytearray(), None, time.monotonic()+25
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    try:
        while selector.get_map():
            if time.monotonic() >= end:
                failure = "wall_time_limit"
                break
            for key, _ in selector.select(.1):
                data = os.read(key.fileobj.fileno(), 8192)
                if not data:
                    selector.unregister(key.fileobj)
                else:
                    output.extend(data)
                    if len(output) > 64000:
                        failure = "output_limit"
                        break
            if failure:
                break
        if failure:
            os.killpg(process.pid, 9)
        code = process.wait(timeout=2)
    finally:
        selector.close()
        if process.poll() is None:
            os.killpg(process.pid, 9)
            process.wait(timeout=2)
        process.stdout.close()
    artifacts, total, visited = {}, 0, 0
    if code == 0 and failure is None:
        for current, directories, files in os.walk("/work", followlinks=False):
            visited += len(directories)+len(files)
            if visited > 256:
                raise ValueError("too many artifact entries")
            for item in directories:
                if Path(current, item).is_symlink():
                    raise ValueError("artifact symlink")
            for item in files:
                path = Path(current, item)
                metadata = path.lstat()
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise ValueError("artifact must be a regular file")
                total += metadata.st_size
                if total > 2_000_000 or len(artifacts) >= 64:
                    raise ValueError("artifact limit")
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as stream:
                    content = stream.read(2_000_001)
                if len(content) != metadata.st_size:
                    raise ValueError("artifact changed during capture")
                artifacts[str(path.relative_to("/work"))] = base64.b64encode(content).decode()
    print(json.dumps({"protocol": 1, "exit_status": code, "failure": failure,
                      "stdout": output[:64000].decode("utf-8", "replace"), "files": artifacts}))


if __name__ == "__main__":
    main()
