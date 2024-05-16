import os
import time
import subprocess
from subprocess import run
from util.toml import update_toml
from invoke import task

def run_factory_command_with_config(config, command, background=False):
    config_flag = "--config {}".format(config) if config else ""
    cmd = "sudo kata-runtime {} factory {}".format(config_flag, command)
    if not background:
        run(cmd, shell=True, check=True)
    else:
        subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        time.sleep(2)
        run_factory_command_with_config(config, "status")


def do_background_init(config):
    run_factory_command_with_config(config, "init", background=True)

def do_destroy_cache(config):
    run_factory_command_with_config(config, "destroy")

@task 
def background_init(ctx, config=None):
    do_background_init(config)

@task
def init(ctx, config=None):
    run_factory_command_with_config(config, "init")

@task
def status(ctx, config=None):
    run_factory_command_with_config(config, "status")

@task
def destroy(ctx, config=None):
    do_destroy_cache(config)

def update_vm_cache_number(config, cache_number):
    updates_toml_string="""
    [factory]
    vm_cache_number = {cache_number}
    """.format(cache_number=cache_number)
    update_toml(config, updates_toml_string)

def do_enable_vm_cache(config=None, cache_number=3):
    if not config or not os.path.isfile(config):
        raise ValueError("Please pass in a valid path for the config file")
    if cache_number < 1:
        raise ValueError("Cannot enable VM Cache with a non-positive cache_number")
    update_vm_cache_number(config, cache_number)

def do_disable_vm_cache(config=None):
    if not config or not os.path.isfile(config):
        raise ValueError("Please pass in a valid path for the config file")
    update_vm_cache_number(config, 0)

@task 
def enable(ctx, config=None, cache_number=3):
    do_enable_vm_cache(config, cache_number)

@task
def disable(ctx, config=None):
    do_disable_vm_cache(config)


