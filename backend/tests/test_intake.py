"""Phase 3 tests: field intake endpoints + evidence pointers."""
from __future__ import annotations

import io

import pandas as pd
from conftest import auth, first_project_id, login


def make_pdf(text: str) -> bytes:
    """Minimal single-page PDF with a text-drawing content stream."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        None,  # content stream, built below
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects[3] = b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"

    out = b"%PDF-1.4\n"
    offsets: list[int] = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF"
    ).encode()
    return out


def submit_text(client, token, project_id, text, source="text", pointer=None):
    return client.post(
        "/api/reports/text",
        headers=auth(token),
        json={
            "project_id": project_id,
            "raw_text": text,
            "source_type": source,
            "pointer": pointer or {},
        },
    )


def test_field_submits_text_report_stores_raw_and_pointer(client):
    token = login(client, "field")["access_token"]
    pid = first_project_id(client, token)
    resp = submit_text(
        client,
        token,
        pid,
        "Installed 24-inch spool pieces rack bays 1 to 3. Hydrotest pending.",
        pointer={"timestamp": "2026-09-25T08:31:00Z"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["raw_text"].startswith("Installed 24-inch spool")
    assert body["source_type"] == "text"
    assert body["pointer"]["timestamp"] == "2026-09-25T08:31:00Z"
    assert body["user_id"] and body["id"]


def test_submit_requires_field_role(client):
    planner = login(client, "planner")["access_token"]
    pm = login(client, "pm")["access_token"]
    pid = first_project_id(client, planner)
    for token in (planner, pm):
        assert submit_text(client, token, pid, "should be rejected").status_code == 403
    assert client.post("/api/reports/text", json={"project_id": 1, "raw_text": "x"}).status_code == 401


def test_empty_text_rejected(client):
    token = login(client, "field")["access_token"]
    pid = first_project_id(client, token)
    resp = submit_text(client, token, pid, "   ")
    assert resp.status_code == 400


def test_unknown_project_404(client):
    token = login(client, "field")["access_token"]
    resp = submit_text(client, token, 999999, "some work done")
    assert resp.status_code == 404


def test_txt_file_upload_stores_text_and_char_pointer(client):
    token = login(client, "field")["access_token"]
    pid = first_project_id(client, token)
    content = b"Area C grounding grid installed and ready for test.\n"
    resp = client.post(
        "/api/reports/file",
        headers=auth(token),
        files={"file": ("notes.txt", content, "text/plain")},
        data={"project_id": str(pid)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_type"] == "txt"
    assert body["raw_text"] == content.decode()
    assert body["filename"] == "notes.txt"
    assert body["pointer"]["chars"] == len(content)


def test_excel_file_upload_has_sheet_and_row_pointer(client):
    token = login(client, "field")["access_token"]
    pid = first_project_id(client, token)
    df = pd.DataFrame([["DPR day report", "", ""], ["Area B piping", "60%", "on track"]])
    buf = io.BytesIO()
    df.to_excel(buf, index=False, sheet_name="DPR", header=False)
    resp = client.post(
        "/api/reports/file",
        headers=auth(token),
        files={"file": ("dpr.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"project_id": str(pid)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_type"] == "excel"
    assert body["pointer"] == {"sheet": "DPR", "rows": {"start": 1, "end": 2}}
    assert "R1:" in body["raw_text"] and "Area B piping" in body["raw_text"]


def test_pdf_file_upload_stores_page_pointer(client):
    token = login(client, "field")["access_token"]
    pid = first_project_id(client, token)
    resp = client.post(
        "/api/reports/file",
        headers=auth(token),
        files={"file": ("report.pdf", make_pdf("Pipework in Area B complete"), "application/pdf")},
        data={"project_id": str(pid)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["source_type"] == "pdf"
    assert "Pipework in Area B complete" in body["raw_text"]
    assert body["pointer"]["pages"] == [1]
    off = body["pointer"]["page_offsets"][0]
    assert off["page"] == 1
    # the pointer must actually locate the evidence inside raw_text
    assert body["raw_text"][off["start"] : off["end"]] == "Pipework in Area B complete"


def test_multi_tab_excel_keeps_every_sheet_as_evidence(client):
    """A DPR workbook with several tabs must not lose the tabs we didn't open."""
    token = login(client, "field")["access_token"]
    pid = first_project_id(client, token)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame([["DPR", ""], ["Area B piping", "60%"]]).to_excel(
            writer, index=False, header=False, sheet_name="DPR"
        )
        pd.DataFrame([["Backlog", ""], ["Electrical", "3 items"]]).to_excel(
            writer, index=False, header=False, sheet_name="Backlog"
        )
    resp = client.post(
        "/api/reports/file",
        headers=auth(token),
        files={
            "file": (
                "dpr.xlsx",
                buf.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        data={"project_id": str(pid)},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    sheets = body["pointer"]["sheets"]
    assert [s["sheet"] for s in sheets] == ["DPR", "Backlog"]
    assert all(s["start"] == 1 for s in sheets)
    assert "DPR!R1:" in body["raw_text"] and "Backlog!R2:" in body["raw_text"]
    assert "Electrical" in body["raw_text"], "the second tab's rows were dropped"


def test_unsupported_file_type_rejected(client):
    token = login(client, "field")["access_token"]
    pid = first_project_id(client, token)
    resp = client.post(
        "/api/reports/file",
        headers=auth(token),
        files={"file": ("photo.png", b"\x89PNG", "image/png")},
        data={"project_id": str(pid)},
    )
    assert resp.status_code == 400
    assert "Unsupported file type" in resp.json()["detail"]


def test_field_sees_only_own_reports_others_see_all(client):
    t1 = login(client, "field")["access_token"]
    t2 = login(client, "field2")["access_token"]
    planner = login(client, "planner")["access_token"]
    pid = first_project_id(client, t1)

    r1 = submit_text(client, t1, pid, "report one by field user")
    r2 = submit_text(client, t2, pid, "report two by other field user")
    assert r1.status_code == 201 and r2.status_code == 201

    mine = client.get("/api/reports", headers=auth(t1)).json()
    assert {r["id"] for r in mine} == {r1.json()["id"]}

    theirs = client.get("/api/reports", headers=auth(t2)).json()
    assert {r["id"] for r in theirs} == {r2.json()["id"]}

    all_reports = client.get("/api/reports", headers=auth(planner)).json()
    ids = {r["id"] for r in all_reports}
    assert r1.json()["id"] in ids and r2.json()["id"] in ids

    assert client.get("/api/reports").status_code == 401
