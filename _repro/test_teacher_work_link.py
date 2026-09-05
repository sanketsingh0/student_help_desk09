"""
Test Teacher Panel Google Drive submitted work link handling.

Verifies that:
1. The "View submitted work" button uses a direct external link (not iframe/embed)
2. The link opens the ORIGINAL submitted URL (not a transformed /preview URL)
3. The link uses target="_blank" with rel="noopener noreferrer"
4. No iframe or embed code exists for submitted work
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import app as appmod

client = appmod.app.test_client()

# A realistic Google Drive URL that a student might submit
DRIVE_URL = "https://drive.google.com/file/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ/view?usp=sharing"

def setup():
    """Log in as admin (who also has teacher access) and seed a task with a Drive link."""
    # Log in
    resp = client.post("/login", data={"email": "sanketsingh9186@gmail.com", "password": "@Sanket918616"}, follow_redirects=True)
    assert resp.status_code == 200, f"Login failed: {resp.status_code}"

    # Create a student user first
    from pathlib import Path
    import sqlite3
    db_path = Path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "studyspace.db"))
    con = sqlite3.connect(db_path)
    # Check if test student exists
    row = con.execute("SELECT id FROM users WHERE email=?", ("teststudent@example.com",)).fetchone()
    if not row:
        con.execute(
            "INSERT INTO users (name, email, password, is_admin, is_teacher, student_id) VALUES (?,?,?,?,?,?)",
            ("Test Student", "teststudent@example.com", "hashed_pw", 0, 0, "TEST001")
        )
        con.commit()
    student_row = con.execute("SELECT id FROM users WHERE email=?", ("teststudent@example.com",)).fetchone()
    student_id = student_row[0]

    # Add a task with a Google Drive link
    con.execute(
        """INSERT INTO student_tasks (student_id, subject_code, category, title, description, work_link, status, progress, student_name, student_roll, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (student_id, "CS101", "Assignment", "Test Task", "Test description", DRIVE_URL, "pending", 0, "Test Student", "TEST001", "2024-01-01 00:00:00", "2024-01-01 00:00:00")
    )
    con.commit()
    con.close()
    return student_id

def test_teacher_panel_link_attributes():
    """Verify the View submitted work link has correct attributes."""
    resp = client.get("/teacher", follow_redirects=True)
    assert resp.status_code == 200, f"Teacher panel failed: {resp.status_code}"
    body = resp.get_data(as_text=True)

    # 1. Link must use target="_blank"
    assert 'target="_blank"' in body, "Link missing target='_blank'"

    # 2. Link must use rel="noopener noreferrer" (not just "noopener")
    assert 'rel="noopener noreferrer"' in body, "Link missing rel='noopener noreferrer'"

    # 3. The ORIGINAL submitted URL must be in the href (not transformed)
    assert f'href="{DRIVE_URL}"' in body, f"Original URL not found in link. Expected: href=\"{DRIVE_URL}\""

    # 4. No iframe should exist for embedding
    assert "<iframe" not in body.lower(), "iframe found - should use direct link"

    # 5. No embed/preview URL transformation
    assert "/preview" not in body, "URL was transformed to /preview"
    assert "embed" not in body.lower(), "embed found - should use direct link"

    # 6. The link text should be present
    assert "View submitted work" in body, "View submitted work link text missing"

    print("[PASS] Teacher panel link has correct attributes")

def test_link_opens_new_tab():
    """Verify the link will open in a new tab (target=_blank + rel=noopener noreferrer)."""
    resp = client.get("/teacher", follow_redirects=True)
    body = resp.get_data(as_text=True)

    # Find the work-link and verify its attributes
    import re
    link_pattern = r'<a[^>]*class="work-link"[^>]*href="([^"]*)"[^>]*target="([^"]*)"[^>]*rel="([^"]*)"[^>]*>'
    match = re.search(link_pattern, body)
    assert match, "Could not find work-link with expected pattern"

    href, target, rel = match.groups()
    assert href == DRIVE_URL, f"href mismatch: {href}"
    assert target == "_blank", f"target mismatch: {target}"
    assert rel == "noopener noreferrer", f"rel mismatch: {rel}"

    print("[PASS] Link opens in new tab with correct attributes")

def test_no_url_transformation():
    """Verify the original URL is preserved without transformation."""
    resp = client.get("/teacher", follow_redirects=True)
    body = resp.get_data(as_text=True)

    # The URL should be exactly as submitted
    assert DRIVE_URL in body, "Original URL not preserved"

    # Common URL transformations that should NOT happen
    bad_transforms = [
        "/preview",
        "/edit?usp=sharing",
        "embed.google.com",
        "docs.google.com/uc?id=",
    ]
    for bad in bad_transforms:
        assert bad not in body, f"URL was transformed: found '{bad}'"

    print("[PASS] URL is preserved without transformation")

def test_mobile_menu_not_interfering():
    """Verify the work-link is outside the mobile nav overlay."""
    resp = client.get("/teacher", follow_redirects=True)
    body = resp.get_data(as_text=True)

    # The work-link should NOT be inside the mobile-nav-overlay
    overlay_start = body.find('id="mobile-nav-overlay"')
    work_link_pos = body.find('View submitted work')
    assert work_link_pos > overlay_start or overlay_start == -1, "Work link should be outside mobile overlay"

    print("[PASS] Work link is outside mobile nav overlay")

if __name__ == "__main__":
    setup()
    print("=== Teacher Work Link Tests ===")
    test_teacher_panel_link_attributes()
    test_link_opens_new_tab()
    test_no_url_transformation()
    test_mobile_menu_not_interfering()
    print("\n=== ALL TESTS PASSED ===")
