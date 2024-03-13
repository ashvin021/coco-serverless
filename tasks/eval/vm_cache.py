
from glob import glob
import json
from invoke import task
from tasks.util.containerd import (
    get_journalctl_containerd_logs,
    get_ts_for_containerd_event,
)
from tasks.util.nerdctl import run_nerdctl_command
from time import sleep, time
from datetime import datetime
import subprocess

NERDCTL_KATA_RUNTIME = "io.containerd.kata.v2"

def do_run_kata_nerdctl(num_run: int, image: str):
    name = f"temp-kata-{num_run}"
    start_ts = time()

    # Silently start
    nerdctl_cmd = "run --runtime \"{}\" --name {} -dt {}".format(NERDCTL_KATA_RUNTIME, name, image)
    output = run_nerdctl_command(nerdctl_cmd, capture_output=True)

    assert isinstance(output, str) # we know this since capture output is set to True
    sandbox_id = output.splitlines()[-1]

    return sandbox_id, name

def do_rm_kata_nerdctl(sandbox_id):
    run_nerdctl_command(f"rm -f {sandbox_id}", capture_output=True)

def get_start_time(sandbox_id, logs, lower_bound):
    starting_ts = get_ts_for_containerd_event("Starting VM", sandbox_id, lower_bound, logs=logs)
    started_ts = get_ts_for_containerd_event("VM started", sandbox_id, lower_bound, logs=logs)
    return started_ts - starting_ts, started_ts

def do_measure_start_times(runs, image, log_output) -> list[float]:
    start_times = []
    sandbox_ids = []

    try:

        start = time()
        for i in range(runs):
            s_id, _ = do_run_kata_nerdctl(i, image)
            sleep(3)

            print(f"started {s_id}")
            sandbox_ids.append(s_id)
        end = time()

        sleep(1)

        # Use journalctl to fetch kata debug logs
        logs = get_journalctl_containerd_logs(since=datetime.fromtimestamp(start), until=datetime.fromtimestamp(end))
        if log_output:
            with open(log_output, 'w') as f:
                f.writelines([json.dumps(json.loads(l), indent=2) + '\n' for l in logs])

        # Measure start times using the logs
        for s_id in sandbox_ids:
            time_to_start, start = get_start_time(s_id, logs, start)
            start_times.append(time_to_start)

    finally:
        for s_id in sandbox_ids:
            do_rm_kata_nerdctl(s_id)
            print(f"removed {s_id}")

    return start_times



@task
def run(ctx, runs=1, log_output=None, no_cache=False):

    no_vm_cache = []
    with_vm_cache = []

    image = "alpine"

    no_vm_cache = do_measure_start_times(runs, image, log_output)

    if no_cache:
        print(f"Start times without cache: {no_vm_cache}")
        return

    subprocess.run("sudo kata-runtime factory init > /dev/null 2>&1 &", shell=True)
    subprocess.run("stty sane", shell=True)

    try:
        with_vm_cache = do_measure_start_times(runs, image, log_output)
    finally:
        subprocess.run("sudo kata-runtime factory destroy", shell=True)

    print(f"Start times without cache: {no_vm_cache}")
    print(f"Start times with cache: {with_vm_cache}")






