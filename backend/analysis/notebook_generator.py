"""
Generate a self-contained Jupyter notebook from video analysis results.

The notebook embeds the angle data directly (as JSON) so it can be
downloaded and opened offline with no backend dependency.  It produces:

  1. Per-angle time-series plots (left vs right on same axes)
  2. Stride phase markers (vertical lines at contact / toe-off)
  3. Form problem annotations on plots (problem frames marked)
  4. Summary statistics table
  5. Cadence report
  6. Form problems report with recommendations
"""

from __future__ import annotations

import json

import nbformat
from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell

from schemas.analyze import AnalysisResult


def generate_notebook(result: AnalysisResult) -> nbformat.NotebookNode:
    """Build a .ipynb NotebookNode from an ``AnalysisResult``."""
    nb = new_notebook()
    nb.metadata.kernelspec = {
        "display_name": "Python 3",
        "language": "python",
        "name": "python3",
    }

    # ── Serialize data into the notebook ─────────────────────────────
    frame_data = [
        {
            "frame": fa.frame_number,
            "ts_ms": fa.timestamp_ms,
            "angles": {k: v.model_dump() for k, v in fa.angles.items()},
        }
        for fa in result.frame_angles
    ]

    summary_data = [s.model_dump() for s in result.summary]

    stride_data = [e.model_dump() for e in result.stride_events]
    stride_summary_data = [s.model_dump() for s in result.stride_summary]

    form_data = result.form_analysis.model_dump() if result.form_analysis else None

    # ── Cell 1: Title ────────────────────────────────────────────────
    score_line = ""
    if result.form_analysis:
        score_line = f"- **Strike Pattern:** {result.form_analysis.strike_pattern}\n"

    nb.cells.append(new_markdown_cell(
        f"# PaceVision Analysis Report\n\n"
        f"- **Job ID:** `{result.job_id}`\n"
        f"- **Total frames:** {result.total_frames}\n"
        f"- **Analyzed frames:** {result.analyzed_frames}\n"
        f"- **Video FPS:** {result.video_fps}\n"
        f"- **Processing time:** {result.duration_sec:.1f}s\n"
        f"{score_line}"
    ))

    # ── Cell 2: Setup + embedded data ────────────────────────────────
    nb.cells.append(new_code_cell(
        "import json\n"
        "import matplotlib.pyplot as plt\n"
        "import matplotlib.patches as mpatches\n"
        "import numpy as np\n"
        "\n"
        "plt.rcParams.update({\n"
        '    "figure.figsize": (14, 5),\n'
        '    "axes.grid": True,\n'
        '    "grid.alpha": 0.3,\n'
        '    "font.size": 11,\n'
        "})\n"
        "\n"
        f"frame_data = json.loads({json.dumps(json.dumps(frame_data))})\n"
        f"summary_data = json.loads({json.dumps(json.dumps(summary_data))})\n"
        f"stride_events = json.loads({json.dumps(json.dumps(stride_data))})\n"
        f"stride_summary = json.loads({json.dumps(json.dumps(stride_summary_data))})\n"
        f"form_data = json.loads({json.dumps(json.dumps(form_data))})\n"
        f"video_fps = {result.video_fps}\n"
        "\n"
        "# Parse angle time-series\n"
        "angle_series = {}  # {angle_name: {frames: [], values: []}}\n"
        "for fd in frame_data:\n"
        "    for name, info in fd['angles'].items():\n"
        "        if name not in angle_series:\n"
        "            angle_series[name] = {'frames': [], 'values': [], 'ts': []}\n"
        "        angle_series[name]['frames'].append(fd['frame'])\n"
        "        angle_series[name]['values'].append(info['value_deg'])\n"
        "        angle_series[name]['ts'].append(fd['ts_ms'] / 1000.0)\n"
        "\n"
        "# Collect problem frames for annotation\n"
        "problem_frames = {}  # {problem_id: set of frame numbers}\n"
        "if form_data and form_data.get('problems'):\n"
        "    for p in form_data['problems']:\n"
        "        problem_frames[p['problem_id']] = set(p.get('frames', []))\n"
        "\n"
        "print(f'Loaded {len(frame_data)} frames, {len(angle_series)} angle channels')\n"
        "if form_data:\n"
        "    print(f'Problems detected: {len(form_data.get(\"problems\", []))}')\n"
    ))

    # ── Cell 3: Per-angle L vs R plots ───────────────────────────────
    nb.cells.append(new_markdown_cell("## Angle Time-Series (Left vs Right)"))

    nb.cells.append(new_code_cell(
        "# Contact frames for vertical markers\n"
        "contact_frames = {}\n"
        "toe_off_frames = {}\n"
        "for ev in stride_events:\n"
        "    side = ev['side']\n"
        "    if ev['phase'] == 'initial_contact':\n"
        "        contact_frames.setdefault(side, []).append(ev['frame_number'])\n"
        "    elif ev['phase'] == 'toe_off':\n"
        "        toe_off_frames.setdefault(side, []).append(ev['frame_number'])\n"
        "\n"
        "# Problem frames relevant to each angle\n"
        "angle_problem_map = {\n"
        "    'knee_flexion': ['overstriding'],\n"
        "    'hip_flexion': ['insufficient_hip_extension'],\n"
        "    'trunk_lean': ['excessive_trunk_lean', 'insufficient_trunk_lean'],\n"
        "    'ankle_dorsiflexion': ['heel_strike'],\n"
        "    'arm_swing': ['arm_swing_stiff', 'arm_swing_excessive', 'arm_swing_asymmetry'],\n"
        "}\n"
        "\n"
        "base_angles = ['knee_flexion', 'hip_flexion', 'trunk_lean',\n"
        "               'ankle_dorsiflexion', 'arm_swing']\n"
        "\n"
        "fig, axes = plt.subplots(len(base_angles), 1, figsize=(16, 4 * len(base_angles)),\n"
        "                         sharex=True)\n"
        "\n"
        "for ax, base in zip(axes, base_angles):\n"
        "    left_key = f'left_{base}'\n"
        "    right_key = f'right_{base}'\n"
        "\n"
        "    # Plot left side\n"
        "    if left_key in angle_series:\n"
        "        s = angle_series[left_key]\n"
        "        ax.plot(s['frames'], s['values'], color='#2979FF',\n"
        "                linewidth=1.5, label='Left', alpha=0.9)\n"
        "\n"
        "    # Plot right side\n"
        "    if right_key in angle_series:\n"
        "        s = angle_series[right_key]\n"
        "        ax.plot(s['frames'], s['values'], color='#FF6D00',\n"
        "                linewidth=1.5, label='Right', alpha=0.9)\n"
        "\n"
        "    # Mark problem frames with red dots\n"
        "    related_problems = angle_problem_map.get(base, [])\n"
        "    pf_set = set()\n"
        "    for pid in related_problems:\n"
        "        pf_set |= problem_frames.get(pid, set())\n"
        "    if pf_set:\n"
        "        for side_key, colour in [(left_key, '#D32F2F'), (right_key, '#E64A19')]:\n"
        "            if side_key in angle_series:\n"
        "                s = angle_series[side_key]\n"
        "                pf_frames = [f for f in s['frames'] if f in pf_set]\n"
        "                pf_vals = [s['values'][s['frames'].index(f)] for f in pf_frames]\n"
        "                if pf_frames:\n"
        "                    ax.scatter(pf_frames, pf_vals, color=colour, s=30,\n"
        "                              zorder=5, label='Problem frame', marker='v')\n"
        "\n"
        "    # Stride phase markers\n"
        "    for cf in contact_frames.get('left', []):\n"
        "        ax.axvline(cf, color='#2979FF', linestyle=':', alpha=0.3, linewidth=0.8)\n"
        "    for cf in contact_frames.get('right', []):\n"
        "        ax.axvline(cf, color='#FF6D00', linestyle=':', alpha=0.3, linewidth=0.8)\n"
        "\n"
        "    ax.set_ylabel('Degrees')\n"
        "    ax.set_title(base.replace('_', ' ').title(), fontweight='bold')\n"
        "    ax.legend(loc='upper right', fontsize=9)\n"
        "\n"
        "axes[-1].set_xlabel('Frame')\n"
        "plt.suptitle('Angle Changes Over Time — Left (blue) vs Right (orange)',\n"
        "             fontsize=14, fontweight='bold', y=1.01)\n"
        "plt.tight_layout()\n"
        "plt.show()\n"
    ))

    # ── Cell 4: Summary table ────────────────────────────────────────
    nb.cells.append(new_markdown_cell("## Summary Statistics"))

    nb.cells.append(new_code_cell(
        "print(f\"{'Angle':<30s} {'Mean':>7s} {'Min':>7s} {'Max':>7s} {'Std':>7s}\")\n"
        "print('-' * 55)\n"
        "for s in summary_data:\n"
        "    print(f\"{s['name']:<30s} {s['mean_deg']:7.1f} {s['min_deg']:7.1f} \"\n"
        "          f\"{s['max_deg']:7.1f} {s['std_deg']:7.1f}\")\n"
    ))

    # ── Cell 5: Form Problems Report ────────────────────────────────
    nb.cells.append(new_markdown_cell("## Form Analysis"))

    nb.cells.append(new_code_cell(
        "if form_data:\n"
        "    print(f\"Strike Pattern: {form_data['strike_pattern']}\")\n"
        "    print()\n"
        "\n"
        "    if form_data.get('asymmetry_index'):\n"
        "        print('Asymmetry Index (L vs R):')\n"
        "        for angle, asi in form_data['asymmetry_index'].items():\n"
        "            flag = ' ⚠' if asi > 10 else ''\n"
        "            print(f'  {angle}: {asi:.1f}%{flag}')\n"
        "        print()\n"
        "\n"
        "    problems = form_data.get('problems', [])\n"
        "    if problems:\n"
        "        print(f'{len(problems)} form problem(s) detected:\\n')\n"
        "        for p in problems:\n"
        "            severity_icon = {'mild': '●', 'moderate': '●●', 'severe': '●●●'}\n"
        "            print(f\"  {severity_icon.get(p['severity'], '?')} {p['display_name']}\")\n"
        "            print(f\"    Severity: {p['severity']} | Side: {p.get('side', 'both')}\")\n"
        "            print(f\"    {p['description']}\")\n"
        "            print(f\"    Occurrence: {p['occurrences']}/{p['total_strides']} strides ({p['occurrence_pct']:.0f}%)\")\n"
        "            print(f\"    Recommendation: {p['recommendation']}\")\n"
        "            print()\n"
        "    else:\n"
        "        print('No form problems detected — good running form!')\n"
        "else:\n"
        "    print('Form analysis not available.')\n"
    ))

    # ── Cell 6: Cadence report ───────────────────────────────────────
    nb.cells.append(new_markdown_cell("## Stride & Cadence Analysis"))

    nb.cells.append(new_code_cell(
        "if stride_summary:\n"
        "    for ss in stride_summary:\n"
        "        print(f\"{ss['side'].title()} leg:\")\n"
        "        print(f\"  Contacts detected: {ss['num_contacts']}\")\n"
        "        print(f\"  Strides:           {ss['num_strides']}\")\n"
        "        print(f\"  Cadence:           {ss['cadence_spm']:.1f} SPM [{ss['cadence_rating']}]\")\n"
        "        print()\n"
        "else:\n"
        "    print('Not enough data to detect stride phases.')\n"
        "\n"
        "# Stride events timeline\n"
        "if stride_events:\n"
        "    print(f\"\\n{'Phase':<20s} {'Side':<8s} {'Frame':>7s} {'Time (s)':>10s}\")\n"
        "    print('-' * 48)\n"
        "    for ev in stride_events[:30]:  # first 30\n"
        "        print(f\"{ev['phase']:<20s} {ev['side']:<8s} \"\n"
        "              f\"{ev['frame_number']:>7d} {ev['timestamp_ms']/1000:>10.2f}\")\n"
        "    if len(stride_events) > 30:\n"
        "        print(f'  ... and {len(stride_events) - 30} more events')\n"
    ))

    return nb
