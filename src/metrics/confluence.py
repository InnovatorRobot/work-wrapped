"""Confluence page list shaping from raw data."""


def _confluence_pages_to_list(pages, base_url):
    """Convert Confluence API content items to our page list (title, space, updated, month, link)."""
    out = []
    for p in pages:
        title = (p.get("title") or "").strip()
        space_obj = p.get("space") or {}
        space_key = space_obj.get("key") or ""
        space_name = space_obj.get("name") or space_key or "?"
        when = ""
        hist = p.get("history") or {}
        if isinstance(hist, dict):
            lu = hist.get("lastUpdated") or {}
            when = (lu.get("when") or "")[:19]
        if not when:
            ver = p.get("version") or {}
            if isinstance(ver, dict):
                when = (ver.get("when") or "")[:19]
        month = when[:7] if len(when) >= 7 else ""
        ver = p.get("version") or {}
        version_number = ver.get("number") if isinstance(ver, dict) else None
        if version_number is not None and not isinstance(version_number, int):
            try:
                version_number = int(version_number)
            except (TypeError, ValueError):
                version_number = None
        link = base_url or ""
        links = p.get("_links") or {}
        webui = links.get("webui") or links.get("base") or ""
        if webui:
            if webui.startswith("http://") or webui.startswith("https://"):
                link = webui
            elif base_url:
                link = base_url.rstrip("/") + "/" + webui.lstrip("/")
            else:
                link = webui
        out.append(
            {
                "id": p.get("id") or "",
                "title": title,
                "space_key": space_key,
                "space": space_name,
                "updated": when[:10] if len(when) >= 10 else "",
                "month": month,
                "link": link,
                "version_number": version_number,
            }
        )
    return out

