from typing import Optional
from subprocess import run

def run_nerdctl_command(cmd, capture_output=False) -> Optional[str]:
    nerdctl_cmd = "sudo nerdctl {}".format(cmd)

    if capture_output:
        return (
            run(nerdctl_cmd, shell=True, capture_output=True).stdout.decode("utf-8").strip()
        )

    run(nerdctl_cmd, shell=True, check=True)
