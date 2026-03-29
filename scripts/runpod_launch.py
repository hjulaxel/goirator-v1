#!/usr/bin/env python3
"""
Launch a Goirator training pod on RunPod.

Prerequisites:
  pip install runpod
  export RUNPOD_API_KEY=your_key

Usage:
  python runpod_launch.py                    # RTX 4090, 1 GPU
  python runpod_launch.py --gpu "A100"       # A100 80GB
  python runpod_launch.py --stop             # Stop running pod
  python runpod_launch.py --resume           # Resume stopped pod
  python runpod_launch.py --status           # Check pod status
"""

import argparse
import os
import sys

try:
    import runpod
except ImportError:
    print("Install runpod: pip install runpod")
    sys.exit(1)


POD_NAME = "goirator-training"

# GPU type IDs (RunPod names)
GPU_TYPES = {
    "4090": "NVIDIA GeForce RTX 4090",
    "A100": "NVIDIA A100 80GB PCIe",
    "A100-SXM": "NVIDIA A100-SXM4-80GB",
    "H100": "NVIDIA H100 80GB HBM3",
    "A40": "NVIDIA A40",
    "L40S": "NVIDIA L40S",
    "3090": "NVIDIA GeForce RTX 3090",
}

SETUP_CMD = (
    "bash -c '"
    "curl -sSL https://raw.githubusercontent.com/hjulaxel/goirator-v1/main/scripts/runpod_setup.sh | bash"
    "'"
)


def find_pod():
    """Find existing goirator pod."""
    pods = runpod.get_pods()
    for pod in pods:
        if pod["name"] == POD_NAME:
            return pod
    return None


def cmd_launch(args):
    gpu_key = args.gpu
    if gpu_key not in GPU_TYPES:
        print(f"Unknown GPU: {gpu_key}. Options: {', '.join(GPU_TYPES.keys())}")
        sys.exit(1)

    existing = find_pod()
    if existing:
        print(f"Pod '{POD_NAME}' already exists (id={existing['id']}, status={existing.get('desiredStatus', '?')})")
        print("Use --resume to restart it, or --stop then delete manually.")
        return

    gpu_type = GPU_TYPES[gpu_key]
    print(f"Creating pod: {POD_NAME}")
    print(f"GPU: {gpu_type}")
    print(f"Image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04")

    pod = runpod.create_pod(
        name=POD_NAME,
        image_name="runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04",
        gpu_type_id=gpu_type,
        gpu_count=1,
        cloud_type="ALL",
        volume_in_gb=200,
        container_disk_in_gb=20,
        volume_mount_path="/workspace",
        min_vcpu_count=4,
        min_memory_in_gb=32,
        ports="22/tcp,8888/http",
        support_public_ip=True,
        start_ssh=True,
        docker_args=SETUP_CMD,
    )

    print(f"\nPod created: id={pod['id']}")
    print(f"SSH will be available once the pod starts.")
    print(f"The setup script will run automatically on start.")
    print(f"\nTo check status: python runpod_launch.py --status")
    print(f"To stop (saves $): python runpod_launch.py --stop")


def cmd_stop(args):
    pod = find_pod()
    if not pod:
        print(f"No pod named '{POD_NAME}' found.")
        return
    runpod.stop_pod(pod["id"])
    print(f"Stopped pod {pod['id']}. Network volume data preserved.")
    print(f"Resume with: python runpod_launch.py --resume")


def cmd_resume(args):
    pod = find_pod()
    if not pod:
        print(f"No pod named '{POD_NAME}' found.")
        return
    runpod.resume_pod(pod["id"])
    print(f"Resumed pod {pod['id']}.")


def cmd_status(args):
    pod = find_pod()
    if not pod:
        print(f"No pod named '{POD_NAME}' found.")
        return
    print(f"Pod: {pod['name']}")
    print(f"  ID: {pod['id']}")
    print(f"  Status: {pod.get('desiredStatus', '?')}")
    print(f"  GPU: {pod.get('machine', {}).get('gpuDisplayName', '?')}")
    runtime = pod.get("runtime", {})
    if runtime:
        ports = runtime.get("ports", [])
        for p in (ports or []):
            if p.get("privatePort") == 22:
                print(f"  SSH: ssh root@{p.get('ip', '?')} -p {p.get('publicPort', '?')}")


def main():
    api_key = os.environ.get("RUNPOD_API_KEY")
    if not api_key:
        print("Set RUNPOD_API_KEY environment variable first.")
        print("Get your key at: https://www.runpod.io/console/user/settings")
        sys.exit(1)

    runpod.api_key = api_key

    parser = argparse.ArgumentParser(description="Launch Goirator training on RunPod")
    parser.add_argument("--gpu", default="4090", help=f"GPU type: {', '.join(GPU_TYPES.keys())} (default: 4090)")
    parser.add_argument("--stop", action="store_true", help="Stop the running pod")
    parser.add_argument("--resume", action="store_true", help="Resume a stopped pod")
    parser.add_argument("--status", action="store_true", help="Check pod status")
    args = parser.parse_args()

    if args.stop:
        cmd_stop(args)
    elif args.resume:
        cmd_resume(args)
    elif args.status:
        cmd_status(args)
    else:
        cmd_launch(args)


if __name__ == "__main__":
    main()
