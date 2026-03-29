# RunPod Tab

The RunPod tab provides pod management features via the RunPod GraphQL API. It has four sub-tabs.

## Billing

Shows your RunPod account summary:

- Current balance
- Total spend
- Credit usage

Also displays storage costs for your network volumes.

## Pods

Lists all your RunPod pods with:

- Pod name and status (running/stopped/exited)
- GPU type and VRAM
- Template name
- Action buttons: start, stop, terminate

For running pods, shows the pod URL. Clicking the pod name opens the Studio web UI if the pod is running on port 8000.

## Storage

Lists all your RunPod network volumes with:

- Volume name and datacenter location
- Size and usage
- Associated pods

## Launch

Create a new pod from the extension:

- **Template** dropdown -- select from your saved RunPod templates
- **Volume** dropdown -- select a network volume to attach
- **GPU** dropdown -- select GPU type
- **Launch** button -- creates and starts the pod

The template, volume, and GPU options are fetched from the RunPod API based on your account.
