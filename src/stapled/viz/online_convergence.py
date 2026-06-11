"""Online EM convergence visualization."""

import sqlite3
import json
from pathlib import Path
from typing import Optional
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib as mpl
import numpy as np
mpl.rcParams.update({
    'figure.facecolor': '#f0f0f0',
    'axes.facecolor': '#f0f0f0',
    'font.family': 'DejaVu Sans',
    'axes.titlesize': 14,
    'axes.titleweight': 'bold',
})


def online_convergence(conn: sqlite3.Connection, out_dir: str) -> Optional[str]:
    """
    Render online EM convergence: LL per batch + reliability trajectory.
    Generates matplotlib PNG charts.

    Args:
        conn: Database connection
        out_dir: Output directory

    Returns:
        Path to PNG file or None if no data
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Load em_state
    cursor = conn.execute("SELECT ll_trace_json FROM em_state WHERE id = 1")
    row = cursor.fetchone()
    if not row or not row[0]:
        return None

    try:
        ll_trace = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        ll_trace = []

    if not ll_trace:
        return None

    # Load reliability snapshots per outlet/batch
    cursor = conn.execute(
        """SELECT batch, outlet_id, reliability FROM reliability_snapshot
           ORDER BY batch, outlet_id"""
    )
    snapshot_rows = cursor.fetchall()

    # Organize by outlet
    reliability_by_outlet = {}
    for batch, outlet_id, reliability in snapshot_rows:
        if outlet_id not in reliability_by_outlet:
            reliability_by_outlet[outlet_id] = []
        reliability_by_outlet[outlet_id].append([batch, reliability])

    # Generate matplotlib figure
    plt.style.use('fivethirtyeight')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

    # Plot 1: Log-likelihood per batch
    ax1.plot(range(len(ll_trace)), ll_trace, 'b-o', linewidth=2, markersize=4)
    ax1.set_xlabel('Batch', fontsize=11)
    ax1.set_ylabel('Log-Likelihood', fontsize=11)
    ax1.set_title('Online EM Convergence: Log-Likelihood per Batch', fontsize=13, fontweight='bold')
    ax1.grid(True, alpha=0.3)

    # Plot 2: Reliability trajectory by outlet
    colors = plt.cm.tab10(np.linspace(0, 1, len(reliability_by_outlet)))
    for (outlet_id, data), color in zip(
        sorted(reliability_by_outlet.items()), colors
    ):
        data_array = np.array(data)
        ax2.plot(
            data_array[:, 0],
            data_array[:, 1],
            "o-",
            label=f"Outlet {outlet_id}",
            color=color,
            linewidth=2,
            markersize=4,
        )

    ax2.set_xlabel('Batch', fontsize=11)
    ax2.set_ylabel('Reliability', fontsize=11)
    ax2.set_title('Outlet Reliability Trajectory', fontsize=13, fontweight='bold')
    ax2.legend(loc='best', fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.set_ylim([0, 1])

    plt.tight_layout()
    fig.text(0.1, 0.01, "Each point = one training batch; rising curve = model learning from streaming data", fontsize=9, color='#555555', style='italic')

    # Create assets directory
    assets_dir = out_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Save PNG
    png_file = assets_dir / "convergence.png"
    fig.savefig(png_file, dpi=100, bbox_inches='tight')
    plt.close(fig)

    # Return relative path
    return "assets/convergence.png"


def reliability_trajectory(conn: sqlite3.Connection, out_dir: str) -> Optional[str]:
    """
    Render reliability trajectory by outlet over batches.

    Args:
        conn: Database connection
        out_dir: Output directory

    Returns:
        Relative path to PNG file or None if no data
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Load reliability snapshots
    cursor = conn.execute(
        """SELECT batch, outlet_id, reliability FROM reliability_snapshot
           ORDER BY batch, outlet_id"""
    )
    snapshot_rows = cursor.fetchall()

    if not snapshot_rows:
        return None

    # Organize by outlet
    reliability_by_outlet = {}
    for row in snapshot_rows:
        if hasattr(row, 'keys'):
            batch, outlet_id, reliability = row['batch'], row['outlet_id'], row['reliability']
        else:
            batch, outlet_id, reliability = row
        if outlet_id not in reliability_by_outlet:
            reliability_by_outlet[outlet_id] = []
        reliability_by_outlet[outlet_id].append([batch, reliability])

    if not reliability_by_outlet:
        return None

    # Generate matplotlib figure
    plt.style.use('fivethirtyeight')
    fig, ax = plt.subplots(figsize=(12, 6))

    colors = plt.cm.tab10(np.linspace(0, 1, len(reliability_by_outlet)))
    for (outlet_id, data), color in zip(sorted(reliability_by_outlet.items()), colors):
        data_array = np.array(data)
        ax.plot(data_array[:, 0], data_array[:, 1], 'o-', label=f'Outlet {outlet_id}',
                color=color, linewidth=2, markersize=4)

    ax.set_xlabel('Batch', fontsize=11)
    ax.set_ylabel('Reliability', fontsize=11)
    ax.set_title('Outlet Reliability Trajectory', fontsize=13, fontweight='bold')
    ax.legend(loc='best', fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_ylim([0, 1])

    plt.tight_layout()
    fig.text(0.1, 0.01, "Reliability score per outlet across training batches; convergence = stable lines", fontsize=9, color='#555555', style='italic')

    # Create assets directory
    assets_dir = out_path / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    # Save PNG
    png_file = assets_dir / "reliability.png"
    fig.savefig(png_file, dpi=100, bbox_inches='tight')
    plt.close(fig)

    # Return relative path
    return "assets/reliability.png"


def _generate_html(ll_trace, reliability_by_outlet) -> str:
    """Generate HTML with embedded JS charts."""
    import json as json_module

    ll_data_json = json_module.dumps([[i, v] for i, v in enumerate(ll_trace)])
    reliability_json = json_module.dumps([
        {"label": f"Outlet {oid}", "data": data}
        for oid, data in sorted(reliability_by_outlet.items())
    ])

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Online EM Convergence</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            margin: 20px;
            background: #f5f5f5;
            color: #333;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            color: #222;
            border-bottom: 2px solid #ddd;
            padding-bottom: 10px;
        }}
        .chart {{
            background: white;
            border-radius: 4px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        h2 {{
            margin-top: 0;
            color: #333;
        }}
        canvas {{
            display: block;
            max-width: 100%;
        }}
        .legend {{
            display: flex;
            flex-wrap: wrap;
            gap: 20px;
            margin: 15px 0;
            font-size: 13px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .color-box {{
            width: 14px;
            height: 14px;
            border-radius: 2px;
        }}
        .stats {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 15px;
            margin: 20px 0;
        }}
        .stat-box {{
            background: #f9f9f9;
            padding: 15px;
            border-radius: 4px;
            border-left: 3px solid #1f77b4;
        }}
        .stat-label {{
            font-size: 12px;
            color: #999;
            text-transform: uppercase;
        }}
        .stat-value {{
            font-size: 24px;
            font-weight: bold;
            color: #333;
            margin-top: 5px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Streaming Dawid-Skene EM Convergence</h1>

        <div class="stats">
            <div class="stat-box">
                <div class="stat-label">Batches Processed</div>
                <div class="stat-value">{len(ll_trace)}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Final Log-Likelihood</div>
                <div class="stat-value">{ll_trace[-1]:.2f}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Outlets Tracked</div>
                <div class="stat-value">{len(reliability_by_outlet)}</div>
            </div>
        </div>

        <div class="chart">
            <h2>Log-Likelihood per Batch</h2>
            <canvas id="llChart" style="height: 400px;"></canvas>
        </div>

        <div class="chart">
            <h2>Reliability Trajectory by Outlet</h2>
            <div class="legend" id="reliabilityLegend"></div>
            <canvas id="reliabilityChart" style="height: 400px;"></canvas>
        </div>
    </div>

    <script>
        function drawLineChart(canvasId, xLabel, yLabel, datasets) {{
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;

            const ctx = canvas.getContext('2d');
            canvas.width = canvas.offsetWidth;
            canvas.height = 400;

            const padding = 60;
            const width = canvas.width - padding * 2;
            const height = canvas.height - padding * 2;

            // Compute bounds
            let minX = Infinity, maxX = -Infinity;
            let minY = Infinity, maxY = -Infinity;

            datasets.forEach(ds => {{
                ds.data.forEach(p => {{
                    minX = Math.min(minX, p[0]);
                    maxX = Math.max(maxX, p[0]);
                    minY = Math.min(minY, p[1]);
                    maxY = Math.max(maxY, p[1]);
                }});
            }});

            const xRange = (maxX - minX) || 1;
            const yRange = (maxY - minY) || 1;
            minX -= xRange * 0.05;
            maxX += xRange * 0.05;
            minY -= yRange * 0.05;
            maxY += yRange * 0.05;

            // Draw background
            ctx.fillStyle = '#fafafa';
            ctx.fillRect(padding, padding, width, height);

            // Draw axes
            ctx.strokeStyle = '#ccc';
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.moveTo(padding, padding);
            ctx.lineTo(padding, canvas.height - padding);
            ctx.lineTo(canvas.width - padding, canvas.height - padding);
            ctx.stroke();

            // Grid lines
            ctx.strokeStyle = '#e8e8e8';
            ctx.lineWidth = 0.5;
            for (let i = 0; i <= 5; i++) {{
                const y = padding + (height / 5) * i;
                ctx.beginPath();
                ctx.moveTo(padding, y);
                ctx.lineTo(canvas.width - padding, y);
                ctx.stroke();

                const val = maxY - (yRange / 5) * i;
                ctx.fillStyle = '#999';
                ctx.font = '11px sans-serif';
                ctx.textAlign = 'right';
                ctx.fillText(val.toFixed(2), padding - 8, y + 4);
            }}

            for (let i = 0; i <= 5; i++) {{
                const x = padding + (width / 5) * i;
                const val = minX + (xRange / 5) * i;
                ctx.fillStyle = '#999';
                ctx.font = '11px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(Math.round(val), x, canvas.height - padding + 18);
            }}

            // Axis labels
            ctx.fillStyle = '#666';
            ctx.font = 'bold 12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(xLabel, canvas.width / 2, canvas.height - 10);
            ctx.save();
            ctx.translate(20, canvas.height / 2);
            ctx.rotate(-Math.PI / 2);
            ctx.textAlign = 'center';
            ctx.fillText(yLabel, 0, 0);
            ctx.restore();

            // Draw lines
            const colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                           '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];

            datasets.forEach((ds, dsIdx) => {{
                ctx.strokeStyle = colors[dsIdx % colors.length];
                ctx.lineWidth = 2;
                ctx.beginPath();

                let first = true;
                ds.data.forEach(p => {{
                    const x = padding + ((p[0] - minX) / (maxX - minX)) * width;
                    const y = canvas.height - padding - ((p[1] - minY) / (maxY - minY)) * height;

                    if (first) {{
                        ctx.moveTo(x, y);
                        first = false;
                    }} else {{
                        ctx.lineTo(x, y);
                    }}
                }});
                ctx.stroke();

                // Points
                ctx.fillStyle = colors[dsIdx % colors.length];
                ds.data.forEach(p => {{
                    const x = padding + ((p[0] - minX) / (maxX - minX)) * width;
                    const y = canvas.height - padding - ((p[1] - minY) / (maxY - minY)) * height;
                    ctx.beginPath();
                    ctx.arc(x, y, 3, 0, 2 * Math.PI);
                    ctx.fill();
                }});
            }});
        }}

        // Plot LL
        const llData = {ll_data_json};
        drawLineChart('llChart', 'Batch', 'Log-Likelihood', [
            {{ label: 'LL', data: llData }}
        ]);

        // Plot reliability
        const reliabilityData = {reliability_json};
        const legend = document.getElementById('reliabilityLegend');
        const colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                       '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'];

        reliabilityData.forEach((ds, idx) => {{
            const item = document.createElement('div');
            item.className = 'legend-item';
            const box = document.createElement('div');
            box.className = 'color-box';
            box.style.backgroundColor = colors[idx % colors.length];
            item.appendChild(box);
            item.appendChild(document.createTextNode(ds.label));
            legend.appendChild(item);
        }});

        drawLineChart('reliabilityChart', 'Batch', 'Reliability', reliabilityData);
    </script>
</body>
</html>"""
    return html
