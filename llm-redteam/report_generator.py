"""
LLM Red-Teaming Framework - Report Generator

Turns scorer.py output into a styled, standalone HTML report - the kind
of artifact you'd actually hand to an encadrant or include in a final
internship report, rather than a raw JSON dump.

Usage:
    python report_generator.py --input scored.json --output report.html
"""

import argparse
import json
from datetime import datetime


SEVERITY_COLORS = {
    "critical": "#b00020",
    "high": "#d9730d",
    "medium": "#b78103",
    "low": "#666666",
    "n/a": "#888888",
    "unknown": "#888888",
}

GRADE_COLORS = {
    "PASS": "#1e7e34",
    "FAIL": "#b00020",
    "ERROR": "#8a2be2",
    "UNKNOWN_EXPECTED": "#888888",
    # Distinct from FAIL/ERROR on purpose -- this is an infra outage
    # (Ollama unreachable), not a security control failing. See scorer.py.
    "BACKEND_UNAVAILABLE": "#b7791f",
}


def esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def render_summary_table(title, breakdown: dict) -> str:
    rows = ""
    for key, counts in sorted(breakdown.items()):
        total = counts.get("pass", 0) + counts.get("fail", 0) + counts.get("error", 0)
        pass_pct = round(100 * counts.get("pass", 0) / total, 1) if total else 0
        rows += f"""
        <tr>
            <td>{esc(key)}</td>
            <td>{counts.get('pass', 0)}</td>
            <td>{counts.get('fail', 0)}</td>
            <td>{counts.get('error', 0)}</td>
            <td>{pass_pct}%</td>
        </tr>"""
    return f"""
    <div class="card">
        <h3>{esc(title)}</h3>
        <table>
            <thead><tr><th>{esc(title)}</th><th>Pass</th><th>Fail</th><th>Error</th><th>Pass rate</th></tr></thead>
            <tbody>{rows}</tbody>
        </table>
    </div>"""


def render_results_table(results: list[dict]) -> str:
    rows = ""
    for r in results:
        grade = r.get("grade", "UNKNOWN")
        color = GRADE_COLORS.get(grade, "#888888")
        sev = r.get("severity", "unknown")
        sev_color = SEVERITY_COLORS.get(sev, "#888888")
        rows += f"""
        <tr>
            <td>{esc(r.get('id'))}</td>
            <td>{esc(r.get('name'))}</td>
            <td>{esc(r.get('category'))}</td>
            <td>{esc(r.get('owasp'))}</td>
            <td><span class="badge" style="background:{sev_color}22;color:{sev_color}">{esc(sev)}</span></td>
            <td>{esc(r.get('expected'))}</td>
            <td>{esc(r.get('status_code'))}</td>
            <td><span class="badge" style="background:{color}22;color:{color}">{esc(grade)}</span></td>
        </tr>"""
    return rows


def generate_html(data: dict) -> str:
    summary = data["summary"]
    results = data["results"]

    pass_rate = round(100 * summary["pass"] / summary["total"], 1) if summary["total"] else 0
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    backend_unavailable = summary.get("backend_unavailable", 0)

    overall_color = "#1e7e34" if summary["fail"] == 0 and summary["error"] == 0 else "#b00020"

    backend_warning_html = ""
    if backend_unavailable:
        backend_warning_html = f"""
  <div class="card" style="border-left: 4px solid #b7791f;">
    <h3 style="color:#b7791f;">AI backend was offline during this run</h3>
    <p style="margin:0; font-size:13px;">
      {backend_unavailable} attack(s) got HTTP 503 (Ollama unreachable) instead of a real
      Gateway verdict and are graded <b>BACKEND_UNAVAILABLE</b>, excluded from the pass/fail
      counts above rather than misreported as security failures. Free up GPU memory / restart
      Ollama and re-run for a complete result set.
    </p>
  </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>LLM Red-Team Report - Secure TT AI Agent</title>
<style>
  body {{
    font-family: Segoe UI, Arial, sans-serif;
    background: #f4f6f8;
    margin: 0;
    padding: 40px;
    color: #1a1a1a;
  }}
  .container {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-size: 24px; color: #003876; margin-bottom: 4px; }}
  .subtitle {{ color: #666; margin-bottom: 24px; font-size: 14px; }}
  .overview {{
    display: flex;
    gap: 16px;
    margin-bottom: 28px;
    flex-wrap: wrap;
  }}
  .stat {{
    background: white;
    border-radius: 10px;
    padding: 18px 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    min-width: 140px;
  }}
  .stat .num {{ font-size: 28px; font-weight: 700; }}
  .stat .label {{ font-size: 12px; color: #666; text-transform: uppercase; letter-spacing: 0.5px; }}
  .card {{
    background: white;
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  }}
  .card h3 {{ margin-top: 0; color: #003876; font-size: 15px; text-transform: uppercase; letter-spacing: 0.5px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 8px 10px; border-bottom: 1px solid #eee; }}
  th {{ color: #666; font-weight: 600; background: #fafbfc; }}
  .badge {{
    display: inline-block;
    padding: 3px 10px;
    border-radius: 10px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
  }}
  .overall {{
    display: inline-block;
    padding: 6px 16px;
    border-radius: 20px;
    color: white;
    font-weight: 700;
    background: {overall_color};
    margin-bottom: 24px;
  }}
  footer {{ color: #999; font-size: 12px; margin-top: 30px; text-align: center; }}
</style>
</head>
<body>
<div class="container">
  <h1>LLM Red-Team Report</h1>
  <div class="subtitle">Secure TT AI Agent - AI Security Gateway validation - generated {generated_at}</div>

  <div class="overall">{"ALL CHECKS PASSED" if summary["fail"] == 0 and summary["error"] == 0 else f"{summary['fail'] + summary['error']} ISSUE(S) FOUND"}</div>
  {backend_warning_html}

  <div class="overview">
    <div class="stat"><div class="num">{summary['total']}</div><div class="label">Total attacks</div></div>
    <div class="stat"><div class="num" style="color:#1e7e34">{summary['pass']}</div><div class="label">Passed</div></div>
    <div class="stat"><div class="num" style="color:#b00020">{summary['fail']}</div><div class="label">Failed</div></div>
    <div class="stat"><div class="num" style="color:#8a2be2">{summary['error']}</div><div class="label">Errors</div></div>
    <div class="stat"><div class="num">{pass_rate}%</div><div class="label">Pass rate</div></div>
    {f'<div class="stat"><div class="num" style="color:#b7791f">{backend_unavailable}</div><div class="label">Backend unavailable</div></div>' if backend_unavailable else ""}
  </div>

  {render_summary_table("By Category", summary["by_category"])}
  {render_summary_table("By Severity", summary["by_severity"])}
  {render_summary_table("By OWASP LLM Top 10 mapping", summary["by_owasp"])}

  <div class="card">
    <h3>All Results</h3>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Name</th><th>Category</th><th>OWASP</th>
          <th>Severity</th><th>Expected</th><th>HTTP Status</th><th>Grade</th>
        </tr>
      </thead>
      <tbody>
        {render_results_table(results)}
      </tbody>
    </table>
  </div>

  <footer>
    Secure TT AI Agent - LLM Red-Teaming Framework - Tunisie Telecom internship project
  </footer>
</div>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="LLM Red-Teaming Framework report generator")
    parser.add_argument("--input", default="scored.json")
    parser.add_argument("--output", default="report.html")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    html = generate_html(data)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Report written to {args.output}")


if __name__ == "__main__":
    main()
