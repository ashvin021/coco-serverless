
from glob import glob
import json
from invoke import task
from matplotlib.patches import Patch
from matplotlib.pyplot import subplots
from os import makedirs
from os.path import basename, exists, join
from pandas import read_csv
from re import search as re_search
from tasks.eval.util.clean import cleanup_after_run
from tasks.eval.util.csv import init_csv_file, write_csv_line
from tasks.eval.util.env import (
    APPS_DIR,
    BASELINES,
    EXPERIMENT_IMAGE_REPO,
    EVAL_TEMPLATED_DIR,
    INTER_RUN_SLEEP_SECS,
    RESULTS_DIR,
    PLOTS_DIR,
)
from tasks.eval.util.pod import (
    get_sandbox_id_from_pod_name,
    wait_for_pod_ready_and_get_ts,
)
from tasks.eval.util.setup import cleanup_baseline, setup_baseline
from tasks.util.containerd import (
    get_event_from_containerd_logs,
    get_journalctl_containerd_logs,
    get_start_end_ts_for_containerd_event,
    get_ts_for_containerd_event,
)
from tasks.util.env import KATA_RUNTIMES
from tasks.util.k8s import template_k8s_file
from tasks.util.kata import get_default_vm_mem_size, update_vm_mem_size, get_sandbox_ids
from tasks.util.kubeadm import get_pod_names_in_ns, run_kubectl_command
from tasks.util.nerdctl import run_nerdctl_command
from tasks.util.ovmf import get_ovmf_boot_events
from time import sleep, time
from datetime import datetime

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

@task
def run(ctx, runs=1, log_output=None):

    image = "alpine"

    start_times = []
    sandbox_ids = []
    initial_start = time()

    try:

        # Start up 10 containers
        start = time()
        for i in range(runs):
            s_id, n = do_run_kata_nerdctl(i, image)
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

    print()
    print(start_times)




