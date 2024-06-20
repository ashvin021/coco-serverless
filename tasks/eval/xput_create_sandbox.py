from datetime import datetime
from glob import glob
from invoke import task
from json import loads as json_loads
from matplotlib.pyplot import subplots
from numpy import array as np_array, mean as np_mean, std as np_std
from os import makedirs
from os.path import basename, exists, join
from pandas import read_csv
from tasks.eval.util.clean import cleanup_after_run
from tasks.eval.util.csv import init_csv_file, write_csv_line
from tasks.eval.util.env import (
    APPS_DIR,
    BASELINES,
    EXPERIMENT_IMAGE_REPO,
    EVAL_TEMPLATED_DIR,
    INTER_RUN_SLEEP_SECS,
    PLOTS_DIR,
    RESULTS_DIR,
)
from tasks.eval.util.setup import setup_baseline
from tasks.util.k8s import template_k8s_file
from tasks.util.kubeadm import get_pod_names_in_ns, run_kubectl_command
from tasks.util.containerd import get_start_end_ts_for_containerd_event
from time import sleep, time
import sys
import os

def disable_print():
    stdout = sys.stdout
    sys.stdout = open(os.devnull, "w")
    return stdout

def do_run(result_file, baseline, num_run, num_par_inst):
    start_ts = time()

    service_files = [
        "apps_xput_{}_service_{}.yaml".format(baseline, i) for i in range(num_par_inst)
    ]
    for service_file in service_files:
        # Capture output to avoid verbose Knative logging
        run_kubectl_command(
            "apply -f {}".format(join(EVAL_TEMPLATED_DIR, service_file)),
            capture_output=True,
        )

    # Get all pod names
    pods = get_pod_names_in_ns("default")
    while len(pods) != num_par_inst:
        sleep(1)
        pods = get_pod_names_in_ns("default")

    # Once we have all pod names, wait for all of them to be ready. We poll the
    # pods in round-robin fashion, but we report the "Ready" timestamp as
    # logged in Kubernetes, so it doesn't matter that much if we take a while
    # to notice that we are done
    ready_pods = {pod: False for pod in pods}
    pods_ready_ts = {pod: None for pod in pods}
    is_done = all(list(ready_pods.values()))
    while not is_done:

        for pod in ready_pods:
            # Skip finished pods
            if ready_pods[pod]:
                continue

            stdout = disable_print()
            ready_ts = None

            try:
                _, ready_ts = get_start_end_ts_for_containerd_event(
                    "RunPodSandbox",
                    pod,
                    timeout_mins=3,
                    num_repeats=1
                )
            except Exception:
                pass

            sys.stdout = stdout

            if ready_ts is not None:
                ready_pods[pod] = True
                pods_ready_ts[pod] = ready_ts
                print(f"ready ts: {ready_ts}")

        is_done = all(list(ready_pods.values()))
        print(ready_pods)
        sleep(3)

    # Calculate the end timestamp as the maximum (latest) timestamp measured
    end_ts = max(list(pods_ready_ts.values()))
    write_csv_line(result_file, num_run, start_ts, end_ts)

    # Remove the pods when we are done
    for service_file in service_files:
        run_kubectl_command(
            "delete -f {}".format(join(EVAL_TEMPLATED_DIR, service_file)),
            capture_output=True,
        )
    for pod in pods:
        run_kubectl_command("delete pod {}".format(pod), capture_output=True)


@task
def run(ctx, baseline=None, num_par=None):
    """
    Measure the latency-throughput of spawning new Knative service instances
    """
    baselines_to_run = list(BASELINES.keys())
    if baseline is not None:
        if baseline not in baselines_to_run:
            print(
                "Unrecognised baseline {}! Must be one in: {}".format(
                    baseline, baselines_to_run
                )
            )
            raise RuntimeError("Unrecognised baseline")
        baselines_to_run = [baseline]

    num_parallel_instances = [1, 2, 4, 8, 16]
    if num_par is not None:
        num_parallel_instances = [int(num_par)]

    results_dir = join(RESULTS_DIR, "xput")
    if not exists(results_dir):
        makedirs(results_dir)

    if not exists(EVAL_TEMPLATED_DIR):
        makedirs(EVAL_TEMPLATED_DIR)

    service_template_file = join(APPS_DIR, "xput", "service.yaml.j2")
    image_name = "csegarragonz/coco-helloworld-py"
    used_images = ["csegarragonz/coco-knative-sidecar", image_name]
    num_runs = 3

    for bline in baselines_to_run:
        baseline_traits = BASELINES[bline]

        # Template as many service files as parallel instances
        for i in range(max(num_parallel_instances)):
            service_file = join(
                EVAL_TEMPLATED_DIR, "apps_xput_{}_service_{}.yaml".format(bline, i)
            )
            template_vars = {
                "image_repo": EXPERIMENT_IMAGE_REPO,
                "image_name": image_name,
                "image_tag": baseline_traits["image_tag"],
                "service_num": i,
            }
            if len(baseline_traits["runtime_class"]) > 0:
                template_vars["runtime_class"] = baseline_traits["runtime_class"]
            template_k8s_file(service_template_file, service_file, template_vars)

        # Second, run any baseline-specific set-up
        setup_baseline(bline, used_images)

        for num_par in num_parallel_instances:
            # Prepare the result file
            result_file = join(results_dir, "{}_{}.csv".format(bline, num_par))
            init_csv_file(result_file, "Run,StartTimeStampSec,EndTimeStampSec")

            for nr in range(num_runs):
                print(
                    "Executing baseline {} ({} parallel srv) run {}/{}...".format(
                        bline, num_par, nr + 1, num_runs
                    )
                )
                do_run(result_file, bline, nr, num_par)
                sleep(INTER_RUN_SLEEP_SECS)
                cleanup_after_run(bline, used_images)


@task
def plot(ctx, baselines):
    """
    Measure the latency-throughput of spawning new Knative service instances
    """
    results_dir = join(RESULTS_DIR, "xput")
    plots_dir = join(PLOTS_DIR, "xput")

    # Collect results
    glob_str = join(results_dir, "*.csv")
    results_dict = {}
    for csv in glob(glob_str):
        baseline = basename(csv).split(".")[0].split("_")[0]
        num_par = basename(csv).split(".")[0].split("_")[1]

        if baseline not in results_dict:
            results_dict[baseline] = {}

        results = read_csv(csv)
        results_dict[baseline][num_par] = {
            "mean": np_mean(
                np_array(results["EndTimeStampSec"].to_list())
                - np_array(results["StartTimeStampSec"].to_list())
            ),
            "sem": np_std(
                np_array(results["EndTimeStampSec"].to_list())
                - np_array(results["StartTimeStampSec"].to_list())
            ),
        }


    blines = list(BASELINES.keys())
    filtered_blines = [l for l in blines if l in baselines]
    if baselines and not filtered_blines:
        print("The baselines you have provided are invalid, continuing with all baselines")
    else:
        blines = filtered_blines

    # Plot throughput-latency
    fig, ax = subplots()
    for bline in blines:
        xs = sorted([int(k) for k in results_dict[bline].keys()])
        ys = [results_dict[bline][str(x)]["mean"] for x in xs]
        ys_err = [results_dict[bline][str(x)]["sem"] for x in xs]
        ax.errorbar(
            xs,
            ys,
            yerr=ys_err,
            fmt="o-",
            label=bline,
        )

    # Misc
    ax.set_xlabel("# concurrent Knative services")
    ax.set_ylabel("Time [s]")
    ax.set_ylim(bottom=0)
    ax.set_title("Throughput-Latency of Pod Sandbox Creation for Knative Services")
    ax.legend()

    for plot_format in ["pdf", "png"]:
        plot_file = join(plots_dir, "xput_create_sandbox.{}".format(plot_format))
        fig.savefig(plot_file, format=plot_format, bbox_inches="tight")
