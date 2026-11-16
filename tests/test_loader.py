from agent.pipeline import load_tickets


def test_loader_is_column_tolerant(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text("Ticket ID,Title,Description\n7,Login broken,Cannot sign in\n", encoding="utf-8")
    t = load_tickets(p)[0]
    assert (t.id, t.subject, t.body) == ("7", "Login broken", "Cannot sign in")
