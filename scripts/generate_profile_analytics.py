#!/usr/bin/env python3
"""Generate a self-hosted GitHub profile analytics SVG from public GitHub API data.

Metrics are intentionally conservative:
- Repository counts/stars/forks use original (non-fork), non-archived public repos.
- Language bars count each repository's primary language (not source-code bytes).
- Activity counts only public events returned by GitHub's recent-events feed in the last 30 days.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

USERNAME = os.environ.get("GITHUB_USERNAME", "sanant456")
OUTPUT = os.environ.get("ANALYTICS_OUTPUT", "assets/github-analytics.svg")
API_BASE = "https://api.github.com"
NOW = dt.datetime.now(dt.timezone.utc)
WINDOW_DAYS = 30


def api_get(path: str):
    url = API_BASE + path
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "github-profile-analytics",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 2:
                raise RuntimeError(f"GitHub API request failed for {path}: {exc}") from exc
            time.sleep(2 ** attempt)


def fetch_repositories():
    repositories = []
    page = 1
    while page <= 5:
        query = urllib.parse.urlencode({
            "type": "owner",
            "sort": "updated",
            "per_page": 100,
            "page": page,
        })
        batch = api_get(f"/users/{urllib.parse.quote(USERNAME)}/repos?{query}")
        if not isinstance(batch, list):
            raise RuntimeError("GitHub repositories API returned an unexpected response.")
        repositories.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return [r for r in repositories if not r.get("private", False) and not r.get("fork") and not r.get("archived")]


def fetch_recent_events():
    # GitHub's public-events endpoint exposes a bounded recent feed, not a complete ledger.
    events = api_get(f"/users/{urllib.parse.quote(USERNAME)}/events/public?per_page=100")
    if not isinstance(events, list):
        raise RuntimeError("GitHub public events API returned an unexpected response.")
    cutoff = NOW - dt.timedelta(days=WINDOW_DAYS)
    recent = []
    for event in events:
        stamp = event.get("created_at")
        if not stamp:
            continue
        try:
            created = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except ValueError:
            continue
        if created >= cutoff:
            recent.append((created, event))
    return recent


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def make_svg(repositories, recent_events) -> str:
    total_repos = len(repositories)
    total_stars = sum(int(r.get("stargazers_count") or 0) for r in repositories)
    total_forks = sum(int(r.get("forks_count") or 0) for r in repositories)
    languages = Counter(r.get("language") for r in repositories if r.get("language"))
    events_by_day = Counter(created.date() for created, _ in recent_events)
    active_days = len(events_by_day)
    event_count = len(recent_events)
    latest_event = max((created for created, _ in recent_events), default=None)

    language_items = languages.most_common(6)
    language_total = sum(languages.values()) or 1

    width, height = 1200, 650
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
        '<title id="title">GitHub analytics for ' + esc(USERNAME) + '</title>',
        '<desc id="desc">Original public repository count, stars, forks, primary language distribution by repository count, and observed public event activity over the last 30 days.</desc>',
        '<defs>',
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#0B1220"/><stop offset="1" stop-color="#14243B"/></linearGradient>',
        '<linearGradient id="blue" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#2563EB"/><stop offset="1" stop-color="#60A5FA"/></linearGradient>',
        '<linearGradient id="violet" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#7C3AED"/><stop offset="1" stop-color="#A78BFA"/></linearGradient>',
        '<linearGradient id="green" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#059669"/><stop offset="1" stop-color="#34D399"/></linearGradient>',
        '<pattern id="dots" width="26" height="26" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r="1" fill="#94A3B8" opacity=".12"/></pattern>',
        '</defs>',
        '<rect x="1" y="1" width="1198" height="648" rx="24" fill="url(#bg)" stroke="#334155" stroke-width="2"/>',
        '<rect x="1" y="1" width="1198" height="648" rx="24" fill="url(#dots)"/>',
        '<text x="42" y="56" fill="#F8FAFC" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="27" font-weight="750" letter-spacing="1">GITHUB ANALYTICS</text>',
        '<text x="44" y="84" fill="#94A3B8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="14">PUBLIC REPOSITORY SNAPSHOT  ·  @' + esc(USERNAME) + '</text>',
        '<rect x="944" y="34" width="210" height="34" rx="17" fill="#102D28" stroke="#34D399" stroke-opacity=".45"/>',
        '<circle cx="965" cy="51" r="5" fill="#34D399"><animate attributeName="opacity" values="1;.35;1" dur="2s" repeatCount="indefinite"/></circle>',
        '<text x="980" y="56" fill="#A7F3D0" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12" font-weight="700">AUTO-UPDATED</text>',
    ]

    cards = [
        ("ORIGINAL PUBLIC REPOS", total_repos, "Non-fork · non-archived", "url(#blue)"),
        ("TOTAL STARS", total_stars, "Across counted repositories", "url(#violet)"),
        ("TOTAL FORKS", total_forks, "Across counted repositories", "url(#green)"),
        ("PUBLIC EVENTS · 30 DAYS", event_count, f"{active_days} active days observed", "url(#blue)"),
    ]
    x_positions = [42, 330, 618, 906]
    for x, (label, value, subtitle, fill) in zip(x_positions, cards):
        parts.extend([
            f'<rect x="{x}" y="112" width="252" height="112" rx="15" fill="#111D30" stroke="#334155"/>',
            f'<rect x="{x}" y="112" width="252" height="4" rx="2" fill="{fill}"/>',
            f'<text x="{x+18}" y="143" fill="#94A3B8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11" font-weight="700" letter-spacing=".9">{esc(label)}</text>',
            f'<text x="{x+18}" y="187" fill="#F8FAFC" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="35" font-weight="750">{value:,}</text>',
            f'<text x="{x+18}" y="208" fill="#64748B" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10">{esc(subtitle)}</text>',
        ])

    # Primary language by repository count.
    parts.extend([
        '<text x="44" y="278" fill="#F8FAFC" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="20" font-weight="700">PRIMARY LANGUAGES</text>',
        '<text x="44" y="300" fill="#94A3B8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12">Count of repositories by GitHub primary-language field · not code-byte share</text>',
    ])
    if language_items:
        for index, (language, count) in enumerate(language_items):
            y = 340 + index * 42
            bar_width = int(500 * count / max(c for _, c in language_items))
            parts.extend([
                f'<text x="44" y="{y}" fill="#CBD5E1" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="13" font-weight="600">{esc(language)}</text>',
                f'<rect x="190" y="{y-14}" width="500" height="12" rx="6" fill="#1E293B"/>',
                f'<rect x="190" y="{y-14}" width="{bar_width}" height="12" rx="6" fill="url(#blue)"/>',
                f'<text x="710" y="{y}" fill="#93C5FD" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="13" font-weight="700">{count} repos · {count/language_total:.0%}</text>',
            ])
    else:
        parts.append('<text x="44" y="352" fill="#94A3B8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="14">No primary-language metadata was returned for the counted repositories.</text>')

    # Daily event bars for the trailing 30 calendar days.
    parts.extend([
        '<text x="795" y="278" fill="#F8FAFC" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="20" font-weight="700">PUBLIC ACTIVITY</text>',
        '<text x="795" y="300" fill="#94A3B8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12">Observed GitHub public events · last 30 days</text>',
    ])
    max_events = max(events_by_day.values(), default=1)
    start_day = NOW.date() - dt.timedelta(days=29)
    chart_x, chart_y, chart_w, chart_h = 800, 338, 350, 142
    parts.append(f'<path d="M{chart_x} {chart_y+chart_h}H{chart_x+chart_w}" stroke="#475569"/>')
    for i in range(30):
        day = start_day + dt.timedelta(days=i)
        val = events_by_day.get(day, 0)
        bar_h = int((val / max_events) * (chart_h - 8)) if val else 2
        x = chart_x + i * 11 + 1
        y = chart_y + chart_h - bar_h
        parts.append(f'<rect x="{x}" y="{y}" width="7" height="{bar_h}" rx="3" fill="url(#violet)" opacity="{0.95 if val else 0.18}"/>')
    parts.extend([
        f'<text x="{chart_x}" y="502" fill="#64748B" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10">{start_day.strftime("%d %b")}</text>',
        f'<text x="{chart_x+chart_w}" y="502" text-anchor="end" fill="#64748B" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10">{NOW.date().strftime("%d %b")}</text>',
        f'<text x="795" y="544" fill="#CBD5E1" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="12">{active_days} days with observed public activity</text>',
    ])

    parts.extend([
        '<path d="M42 568H1158" stroke="#334155"/>',
        '<text x="44" y="600" fill="#94A3B8" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="11">Counts exclude forked and archived public repositories. Activity is based on GitHub’s bounded public event feed, not total contributions.</text>',
        '<text x="44" y="622" fill="#64748B" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="10">Last generated: ' + esc(NOW.strftime("%d %b %Y · %H:%M UTC")) + (f'  ·  Latest observed event: {esc(latest_event.strftime("%d %b %Y"))}' if latest_event else '  ·  No public events in the recent feed') + '</text>',
        '</svg>',
    ])
    return "\n".join(parts)


def main():
    repositories = fetch_repositories()
    recent_events = fetch_recent_events()
    svg = make_svg(repositories, recent_events)
    directory = os.path.dirname(OUTPUT)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as file:
        file.write(svg)
    print(f"Generated {OUTPUT}: {len(repositories)} original public repositories, {len(recent_events)} observed public events in {WINDOW_DAYS} days.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Analytics generation failed: {exc}", file=sys.stderr)
        sys.exit(1)
