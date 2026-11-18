"""Construction et rendu du tableau récapitulatif (texte, Markdown, CSV, HTML)."""

from __future__ import annotations

import csv
import html
import io
from dataclasses import dataclass, field
from datetime import datetime

from .config import CODEC_EFFICIENCY, QUALITY_FACTOR, AppConfig, ModelConfig
from .ladder import DIRECTION_LABEL, NetworkProfile
from .model import (
    SLIDER_MAX_MBPS,
    SLIDER_UNLOCKED_MAX_MBPS,
    ModeTarget,
    best_fps,
    best_per_resolution,
    build_matrix,
    budget_from_capacity,
    max_video_for_budget,
    needs_unlock,
    recommend_codec_short,
    settable_ceiling,
    reference_is_clamped,
)
from .report import CLAMP_NOTE, SLIDER_NOTE, Palette, _table, align_markers

MARK = {"ok": "✓", "marginal": "~", "no": "✗"}
CODEC_LABEL = {"h264": "H.264", "hevc": "HEVC", "av1": "AV1"}


@dataclass
class Table:
    title: str
    headers: list[str]
    rows: list[list[str]]
    aligns: str = ""
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.aligns:
            self.aligns = "l" * len(self.headers)


@dataclass
class Recap:
    title: str
    subtitle: str
    meta: list[tuple[str, str]]
    tables: list[Table]
    footer: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Construction des sections
# --------------------------------------------------------------------------


def _cell(t: ModeTarget | None, plain: bool) -> str:
    if t is None:
        return ""
    if t.verdict == "no":
        return "—" if plain else "— ✗"
    if plain:
        return f"{t.advised_mbps:.0f}"
    flag = " †" if needs_unlock(t.advised_mbps) else ""
    return f"{t.advised_mbps:.0f} {MARK[t.verdict]}{flag}"


def network_table(profile: NetworkProfile) -> Table:
    rows = []
    for p in filter(None, [profile.primary, profile.secondary]):
        rows.append([
            DIRECTION_LABEL.get(p.direction, p.direction).split(" (")[0],
            f"{p.tcp_mbps:.1f}" if p.tcp_mbps is not None else "—",
            f"{p.clean_mbps:.1f}",
            f"{p.loss_pct:.2f}" if p.clean_trial else "—",
            f"{p.jitter_ms:.2f}" if p.clean_trial else "—",
        ])
    notes = []
    if profile.mtu:
        notes.append(
            f"MTU du chemin : {profile.mtu} octets"
            + (f" (méthode : {profile.mtu_method})" if profile.mtu_method else "")
        )
    if profile.ping:
        notes.append(
            f"Latence ICMP : {profile.ping.avg_ms:.2f} ms "
            f"(± {profile.ping.mdev_ms:.2f} ms), perte {profile.ping.loss_pct:.1f} %"
        )
    if profile.primary.sender_limited:
        notes.append("L'émetteur a plafonné avant le réseau : capacité sous-estimée.")
    if profile.primary.ceiling_not_reached:
        notes.append("Aucun palier n'a saturé le lien : la vraie limite est plus haute.")
    return Table(
        title="Lien mesuré",
        headers=["Sens", "TCP brut (Mbps)", "UDP propre (Mbps)", "Perte (%)",
                 "Gigue (ms)"],
        rows=align_markers(rows), aligns="lrrrr", notes=notes,
    )


def matrix_table(budget: float, m: ModelConfig, plain: bool) -> Table:
    framerates = sorted(m.framerates)
    by_key = {(t.width, t.height, t.fps): t for t in build_matrix(budget, m)}
    rows, clamped = [], False
    for name, w, h in m.resolutions:
        if reference_is_clamped(w, h):
            clamped = True
            name += "" if plain else " *"
        row = [name, f"{w}x{h}"]
        row += [_cell(by_key.get((w, h, fps)), plain) for fps in framerates]
        rows.append(row)
    notes = []
    if not plain:
        notes.append("✓ confortable · ~ limite · ✗ hors budget")
        if any("†" in cell for row in rows for cell in row[2:]):
            notes.append(SLIDER_NOTE)
        if clamped:
            notes.append(CLAMP_NOTE)
    return Table(
        title=f"Débit à régler dans Moonlight — {CODEC_LABEL.get(m.codec, m.codec)}, "
              f"préréglage « {m.quality} » (Mbps)",
        headers=["Résolution", "Définition"] + [f"{f} fps" for f in framerates],
        rows=align_markers(rows), aligns="ll" + "r" * len(framerates),
        notes=notes,
    )


def codec_table(budget: float, m: ModelConfig) -> Table:
    """Pour chaque résolution, le meilleur mode tenable selon le codec."""
    codecs = ["h264", "hevc", "av1"]
    rows = []
    clamped = False
    for resolution in m.resolutions:
        name, w, h = resolution
        if reference_is_clamped(w, h):
            clamped = True
            name += " *"
        row = [name, f"{w}x{h}"]
        for codec in codecs:
            variant = ModelConfig(**{**m.__dict__, "codec": codec})
            best = best_fps(resolution, budget, variant)
            if best is None:
                row.append("—")
                continue
            row.append(f"{best.fps} fps · {best.advised_mbps:.0f}"
                       + (" †" if needs_unlock(best.advised_mbps) else ""))
        rows.append(row)
    return Table(
        title="Mode le plus élevé tenable selon le codec (fps · Mbps)",
        headers=["Résolution", "Définition"] + [CODEC_LABEL[c] for c in codecs],
        rows=align_markers(rows), aligns="llrrr",
        notes=["Efficacité relative appliquée : " + ", ".join(
            f"{CODEC_LABEL[c]} ×{CODEC_EFFICIENCY[c]:.2f}" for c in codecs)]
        + ([SLIDER_NOTE] if any("†" in cell for row in rows for cell in row[2:])
           else [])
        + ([CLAMP_NOTE] if clamped else []),
    )


def quality_table(budget: float, m: ModelConfig) -> Table:
    """Ce que chaque préréglage de qualité permet d'atteindre."""
    rows = []
    for preset in sorted(QUALITY_FACTOR, key=QUALITY_FACTOR.get, reverse=True):
        variant = ModelConfig(**{**m.__dict__, "quality": preset})
        candidates = [
            best for best in (
                best_fps(resolution, budget, variant) for resolution in m.resolutions
            ) if best
        ]
        if candidates:
            # Une définition plafonnée afficherait le débit de la 4K : on
            # préfère la plus grande taille dont la référence est réelle.
            best = max(candidates, key=lambda t: (not t.clamped, t.pixel_rate))
            rows.append([
                preset, f"×{QUALITY_FACTOR[preset]:.2f}",
                f"{best.width}x{best.height}", f"{best.fps}",
                f"{best.advised_mbps:.0f}"
                + (" †" if needs_unlock(best.advised_mbps) else ""),
                f"{best.headroom:.2f}×",
            ])
        else:
            rows.append([preset, f"×{QUALITY_FACTOR[preset]:.2f}", "—", "—", "—", "—"])
    return Table(
        title=f"Mode maximal selon le préréglage de qualité ({CODEC_LABEL.get(m.codec, m.codec)})",
        headers=["Préréglage", "Facteur", "Résolution", "fps", "Mbps", "Marge"],
        rows=align_markers(rows), aligns="llrrrr",
        notes=["Le facteur s'applique à la référence Moonlight : « max » vise une "
               "qualité nettement supérieure au défaut, « saver » l'allège."]
        + ([SLIDER_NOTE] if any("†" in row[4] for row in rows) else []),
    )


def best_table(budget: float, m: ModelConfig) -> Table:
    """Le mode le plus élevé tenable pour chaque taille d'écran."""
    rows, clamped, marginal, unlock = [], False, False, False
    for (name, w, h), t in best_per_resolution(build_matrix(budget, m)):
        if t is None:
            rows.append([name, f"{w}x{h}", "—", "—", "—", "hors budget"])
            continue
        clamped = clamped or t.clamped
        marginal = marginal or t.verdict == "marginal"
        unlock = unlock or needs_unlock(t.advised_mbps)
        rows.append([
            name + (" *" if t.clamped else ""),
            f"{w}x{h}",
            f"{t.fps}" + ("" if t.verdict == "ok" else " ~"),
            f"{t.advised_mbps:.0f}" + (" †" if needs_unlock(t.advised_mbps) else ""),
            f"{t.headroom:.2f}×",
            recommend_codec_short(t.advised_mbps, w, h),
        ])
    notes = ["Prenez la ligne de votre écran : au-delà du lien, ce sont la dalle "
             "et le GPU qui limitent."]
    if marginal:
        notes.append("~ mode limite : tenable, sans marge.")
    if unlock:
        notes.append(SLIDER_NOTE)
    if clamped:
        notes.append(CLAMP_NOTE)
    if all(row[2] == "—" for row in rows):
        notes = ["Aucun mode ne tient dans le budget mesuré."]
    return Table(
        title="Mode le plus élevé tenable par taille d'écran",
        headers=["Résolution", "Définition", "fps max", "Mbps à régler",
                 "Marge", "Codec"],
        rows=align_markers(rows), aligns="llrrrl", notes=notes,
    )


SECTIONS = ("network", "matrix", "codecs", "quality", "best")


def build_recap(cfg: AppConfig, budget: float, capacity: float,
                profile: NetworkProfile | None, sections: list[str],
                source: str, plain: bool = False) -> Recap:
    m = cfg.model
    tables: list[Table] = []
    for name in sections:
        if name == "network" and profile is not None:
            tables.append(network_table(profile))
        elif name == "matrix":
            tables.append(matrix_table(budget, m, plain))
        elif name == "codecs":
            tables.append(codec_table(budget, m))
        elif name == "quality":
            tables.append(quality_table(budget, m))
        elif name == "best":
            tables.append(best_table(budget, m))

    meta = [
        ("Source", source),
        ("Capacité UDP propre", f"{capacity:.1f} Mbps"),
        ("Marge de sécurité", f"×{m.safety_margin:.2f}"),
        ("Budget réseau", f"{budget:.1f} Mbps"),
        ("Vidéo maximale", f"{max_video_for_budget(budget, m):.1f} Mbps"),
        ("Curseur Moonlight", f"{SLIDER_MAX_MBPS:.0f} Mbps "
                              f"({SLIDER_UNLOCKED_MAX_MBPS:.0f} si débloqué)"),
        ("Débit maximal réglable", "%.1f Mbps — limité par %s" % settable_ceiling(budget, m)),
        ("FEC Sunshine", f"{m.fec_overhead * 100:.0f} %"),
        ("Audio réservé", f"{m.audio_mbps:.1f} Mbps"),
        ("Codec", CODEC_LABEL.get(m.codec, m.codec)),
        ("Qualité", f"{m.quality} (×{QUALITY_FACTOR.get(m.quality, 1.0):.2f})"),
    ]
    if cfg.active_profile:
        meta.insert(1, ("Profil", cfg.active_profile))
    if m.yuv444:
        meta.append(("Chroma", "4:4:4 (×2)"))
    if m.hdr:
        meta.append(("HDR", "oui (+10 %)"))

    return Recap(
        title="Récapitulatif Moonlight",
        subtitle=datetime.now().strftime("%d/%m/%Y %H:%M"),
        meta=meta, tables=tables,
        footer=[
            "Référence : formule de débit par défaut de Moonlight "
            "(table de pixels interpolée, √(fps/60) au-delà de 60 fps).",
            "Les débits affichés sont les valeurs à saisir dans Moonlight : "
            "la FEC et l'audio sont déjà déduits du budget réseau.",
        ],
    )


# --------------------------------------------------------------------------
# Rendus
# --------------------------------------------------------------------------


def render_text(recap: Recap, palette: Palette) -> str:
    c = palette
    out = [f"{c.bold}{c.cyan}{recap.title}{c.reset} — {c.dim}{recap.subtitle}{c.reset}", ""]
    width = max(len(k) for k, _ in recap.meta)
    for key, value in recap.meta:
        out.append(f"  {c.dim}{key.ljust(width)}{c.reset}  {value}")
    for table in recap.tables:
        out.append("")
        out.append(f"{c.bold}{c.cyan}── {table.title} "
                   f"{'─' * max(3, 60 - len(table.title))}{c.reset}")
        out.append(_table(table.headers, table.rows, table.aligns))
        for note in table.notes:
            out.append(f"  {c.dim}{note}{c.reset}")
    if recap.footer:
        out.append("")
        for line in recap.footer:
            out.append(f"  {c.dim}{line}{c.reset}")
    return "\n".join(out)


def _clean(row: list[str]) -> list[str]:
    """Le remplissage ne sert qu'à aligner le tableau texte."""
    return [cell.strip() for cell in row]


def render_markdown(recap: Recap) -> str:
    out = [f"# {recap.title}", "", f"*{recap.subtitle}*", ""]
    out += ["| Paramètre | Valeur |", "|---|---|"]
    out += [f"| {k} | {v} |" for k, v in recap.meta]
    for table in recap.tables:
        out += ["", f"## {table.title}", ""]
        out.append("| " + " | ".join(table.headers) + " |")
        out.append("|" + "|".join(
            ":--" if a == "l" else "--:" for a in table.aligns) + "|")
        for row in table.rows:
            out.append("| " + " | ".join(_clean(row)) + " |")
        for note in table.notes:
            out += ["", f"> {note}"]
    if recap.footer:
        out.append("")
        out += [f"*{line}*" for line in recap.footer]
    return "\n".join(out) + "\n"


def render_csv(recap: Recap) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", lineterminator="\n")
    writer.writerow([recap.title, recap.subtitle])
    writer.writerow([])
    for key, value in recap.meta:
        writer.writerow([key, value])
    for table in recap.tables:
        writer.writerow([])
        writer.writerow([table.title])
        writer.writerow(table.headers)
        writer.writerows(_clean(row) for row in table.rows)
        for note in table.notes:
            writer.writerow([note])
    return buf.getvalue()


_HTML_CSS = """
:root{--bg:#fbfbfa;--fg:#1d1d1b;--muted:#6b6b66;--line:#e3e3df;--head:#f2f2ef;
--ok:#1a7f4b;--warn:#a16207;--no:#b3261e;--accent:#2f6f8f}
:root:not([data-theme="light"]){@media (prefers-color-scheme:dark){
:root{--bg:#17171a;--fg:#ececea;--muted:#9a9a95;--line:#2f2f34;--head:#202024;
--ok:#4ade80;--warn:#fbbf24;--no:#f87171;--accent:#7dd3fc}}}
*{box-sizing:border-box}
body{margin:0;padding:32px 16px;background:var(--bg);color:var(--fg);
font:15px/1.55 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif}
main{max-width:980px;margin:0 auto}
h1{font-size:1.6rem;margin:0 0 4px}
.sub{color:var(--muted);margin:0 0 24px}
h2{font-size:1.05rem;margin:32px 0 10px;color:var(--accent)}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 16px;margin:0 0 8px;
padding:14px 16px;background:var(--head);border:1px solid var(--line);border-radius:8px}
dt{color:var(--muted)}dd{margin:0;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;border-bottom:1px solid var(--line);text-align:left}
th{background:var(--head);font-weight:600}
td.num,th.num{text-align:right}
tr:hover td{background:var(--head)}
.ok{color:var(--ok)}.warn{color:var(--warn)}.no{color:var(--muted)}
.note{color:var(--muted);font-size:.88rem;margin:8px 0 0}
footer{margin-top:36px;color:var(--muted);font-size:.85rem}
@media(max-width:640px){body{padding:20px 16px}dl{grid-template-columns:1fr}}
"""


def _html_cell(text: str) -> str:
    escaped = html.escape(text)
    # « 154 ✓ † » porte le marqueur après le verdict : on cherche le symbole
    # n'importe où dans la case, pas seulement en fin de chaîne.
    if "✓" in text:
        return f'<span class="ok">{escaped}</span>'
    if "~" in text:
        return f'<span class="warn">{escaped}</span>'
    if "✗" in text or text == "—":
        return f'<span class="no">{escaped}</span>'
    return escaped


def render_html(recap: Recap) -> str:
    parts = [
        "<!doctype html>", '<html lang="fr"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{html.escape(recap.title)}</title>",
        f"<style>{_HTML_CSS}</style></head><body><main>",
        f"<h1>{html.escape(recap.title)}</h1>",
        f'<p class="sub">{html.escape(recap.subtitle)}</p>', "<dl>",
    ]
    for key, value in recap.meta:
        parts.append(f"<dt>{html.escape(key)}</dt><dd>{html.escape(value)}</dd>")
    parts.append("</dl>")

    for table in recap.tables:
        parts.append(f"<h2>{html.escape(table.title)}</h2><table><thead><tr>")
        for i, header in enumerate(table.headers):
            cls = ' class="num"' if table.aligns[i] == "r" else ""
            parts.append(f"<th{cls}>{html.escape(header)}</th>")
        parts.append("</tr></thead><tbody>")
        for row in table.rows:
            parts.append("<tr>")
            for i, cell in enumerate(_clean(row)):
                cls = ' class="num"' if table.aligns[i] == "r" else ""
                parts.append(f"<td{cls}>{_html_cell(cell)}</td>")
            parts.append("</tr>")
        parts.append("</tbody></table>")
        for note in table.notes:
            parts.append(f'<p class="note">{html.escape(note)}</p>')

    if recap.footer:
        parts.append("<footer>" + "<br>".join(
            html.escape(line) for line in recap.footer) + "</footer>")
    parts.append("</main></body></html>")
    return "\n".join(parts) + "\n"


def render_json(recap: Recap) -> str:
    import json as _json

    return _json.dumps({
        "title": recap.title,
        "generated_at": recap.subtitle,
        "meta": dict(recap.meta),
        "tables": [{
            "title": t.title, "headers": t.headers,
            "rows": [_clean(row) for row in t.rows],
            "notes": t.notes,
        } for t in recap.tables],
        "footer": recap.footer,
    }, indent=2, ensure_ascii=False) + "\n"


RENDERERS = {
    "markdown": render_markdown,
    "csv": render_csv,
    "html": render_html,
    "json": render_json,
}
