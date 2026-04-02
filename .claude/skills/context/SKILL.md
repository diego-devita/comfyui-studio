---
name: context
description: Read ALL project context files from .context/ and CLAUDE.md. Use when starting work or when Diego says "leggi il contesto".
---

# Read ALL context

You MUST read every single file in `.context/` and `CLAUDE.md`. No skipping. No summarizing from memory. Actually read each file with the Read tool.

## Step 1: Discover

Scan `.context/` to find all subdirectories. For each subdirectory, count the files. This gives you the total directories (N) and files per directory (M).

Also count CLAUDE.md as a separate item.

## Step 2: Read CLAUDE.md first

Print:
```
(0/N) CLAUDE.md...DONE
```

## Step 3: Read each directory

For each directory, print the header, then read all files and print DONE for each:

```
(1/N) ARCHITECTURE (M files)
    1. README.md...DONE
    2. catalog-redesign.md...DONE
    3. comfyui-internals.md...DONE
    ...
(2/N) CLAUDE (M files)
    1. README.md...DONE
    2. claude-memory-system.md...DONE
    ...
```

Rules:
- N = total number of directories
- M = number of files in that directory
- Print "DONE" only AFTER you have actually read the file with the Read tool
- Read files within each directory in parallel (multiple Read calls at once) for speed
- Print the DONE lines in order after all reads in that batch complete
- If a file fails to read, print "FAILED" instead of "DONE"
- Directories in alphabetical order

## Step 4: Summary

After all files are read, print:

```
Context loaded: X files read from Y directories. Z failed.
```

## IMPORTANT

- Use parallel Read calls within each directory to be fast
- Do NOT skip files you think you already know from earlier in the conversation
- Do NOT summarize — actually invoke the Read tool on every file
- If a directory has subdirectories with files (like tools/pod_run/README.md), read those too and include them in the count
