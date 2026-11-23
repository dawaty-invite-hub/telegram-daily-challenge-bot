"""Daily coding challenge Telegram bot. Pure standard library.
Env: BOT_TOKEN (required), CHALLENGE_HOUR_UTC (default 8), PORT (optional, serves /health).
Commands: /start /today /answer <text> (or just send the answer) /score /hint /help
Everyone who sends /start joins the scoreboard (so you and your friend each do it once).
"""
import os, json, time, sqlite3, threading, urllib.request, urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

TOKEN = os.environ["BOT_TOKEN"]
API = f"https://api.telegram.org/bot{TOKEN}/"
HOUR = int(os.environ.get("CHALLENGE_HOUR_UTC", "8"))
DB = os.environ.get("DB_PATH", "bot.db")

# (question, accepted answers lowercase, hint)
CHALLENGES = [
 ("What does this Python print?\n\nprint(len([x for x in range(10) if x % 3 == 0]))", ["4"], "Multiples of 3 below 10."),
 ("What does this print?\n\nprint('abc'[::-1])", ["cba"], "Slice with step -1."),
 ("What is the output?\n\nprint(2 ** 3 ** 2)", ["512"], "** is right-associative."),
 ("What does this print?\n\nprint(sum(range(1, 101)))", ["5050"], "Gauss."),
 ("What is printed?\n\nprint(list(map(lambda x: x*x, [1,2,3])))", ["[1, 4, 9]", "[1,4,9]"], "Squares."),
 ("What is printed?\n\nprint(10 // 3, 10 % 3)", ["3 1"], "Floor division and remainder."),
 ("What is printed?\n\nprint(bool([]), bool([0]))", ["false true"], "Empty containers are falsy."),
 ("What is the binary of 10 (digits only)?", ["1010"], "8 + 2."),
 ("How many times does 'a' appear in 'banana'? (number)", ["3"], "b-a-n-a-n-a"),
 ("What is printed?\n\nprint(sorted('hello'))", ["['e', 'h', 'l', 'l', 'o']", "['e','h','l','l','o']"], "Sorted gives a list of chars."),
 ("What is printed?\n\nx = [1,2,3]\ny = x\ny.append(4)\nprint(len(x))", ["4"], "Both names point to one list."),
 ("What is printed?\n\nprint(type(3/2).__name__)", ["float"], "/ always gives float."),
 ("What is printed?\n\nprint('a,b,c'.split(',')[-1])", ["c"], "Last item."),
 ("What is printed?\n\nprint(max([3,9,2], key=lambda n: -n))", ["2"], "key flips the ordering."),
]

db = sqlite3.connect(DB, check_same_thread=False)
lock = threading.Lock()
db.executescript("""
CREATE TABLE IF NOT EXISTS users(chat_id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS solved(chat_id INTEGER, day TEXT, pts INTEGER, PRIMARY KEY(chat_id, day));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
""")

def call(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(API + method, data), timeout=60) as r:
        return json.load(r)

def send(chat_id, text):
    try: call("sendMessage", chat_id=chat_id, text=text)
    except Exception as e: print("send failed", e)

def today(): return datetime.now(timezone.utc).strftime("%Y-%m-%d")
def challenge(day=None):
    d = datetime.strptime(day or today(), "%Y-%m-%d").date()
    return CHALLENGES[d.toordinal() % len(CHALLENGES)]

def score_text():
    with lock:
        rows = db.execute("""SELECT u.name, COALESCE(SUM(s.pts),0), COUNT(s.day) FROM users u
            LEFT JOIN solved s ON s.chat_id=u.chat_id GROUP BY u.chat_id ORDER BY 2 DESC""").fetchall()
    if not rows: return "No players yet. Send /start."
    return "Scoreboard\n" + "\n".join(f"{i+1}. {n}: {p} pts ({c} solved)" for i,(n,p,c) in enumerate(rows))

def handle(msg):
    chat = msg["chat"]["id"]; text = (msg.get("text") or "").strip()
    name = msg["from"].get("first_name") or str(chat)
    if not text: return
    cmd, _, rest = text.partition(" ")
    cmd = cmd.split("@")[0].lower()
    if cmd in ("/start", "/help"):
        with lock:
            db.execute("INSERT OR REPLACE INTO users VALUES(?,?)", (chat, name)); db.commit()
        send(chat, f"Hi {name}! A coding challenge arrives every day. Send your answer as a normal message.\n"
                   "First correct answer of the day: 2 pts, a later one: 1 pt. /today /hint /score")
        send(chat, "Today's challenge:\n\n" + challenge()[0]); return
    if cmd == "/today": send(chat, challenge()[0]); return
    if cmd == "/hint": send(chat, "Hint: " + challenge()[2]); return
    if cmd == "/score": send(chat, score_text()); return
    if text.startswith("/"): return
    answer = (rest if cmd == "/answer" else text).strip().lower()
    with lock:
        if not db.execute("SELECT 1 FROM users WHERE chat_id=?", (chat,)).fetchone():
            db.execute("INSERT INTO users VALUES(?,?)", (chat, name))
        if db.execute("SELECT 1 FROM solved WHERE chat_id=? AND day=?", (chat, today())).fetchone():
            send(chat, "You already solved today's. See you tomorrow."); db.commit(); return
        if answer in challenge()[1]:
            first = db.execute("SELECT COUNT(*) FROM solved WHERE day=?", (today(),)).fetchone()[0] == 0
            pts = 2 if first else 1
            db.execute("INSERT INTO solved VALUES(?,?,?)", (chat, today(), pts)); db.commit()
            ok = f"Correct! +{pts} pt{'s' if pts>1 else ''}" + (" (first today)" if first else "")
        else:
            db.commit(); ok = None
    if ok:
        send(chat, ok); send(chat, score_text())
        with lock: others = [r[0] for r in db.execute("SELECT chat_id FROM users WHERE chat_id!=?", (chat,))]
        for o in others: send(o, f"{name} solved today's challenge.")
    else:
        send(chat, "Not quite. Try again or /hint.")

def daily_loop():
    while True:
        try:
            now = datetime.now(timezone.utc)
            if now.hour >= HOUR:
                with lock:
                    sent = db.execute("SELECT v FROM meta WHERE k='sent'").fetchone()
                if not sent or sent[0] != today():
                    with lock:
                        users = [r[0] for r in db.execute("SELECT chat_id FROM users")]
                        db.execute("INSERT OR REPLACE INTO meta VALUES('sent',?)", (today(),)); db.commit()
                    for u in users: send(u, "New daily challenge:\n\n" + challenge()[0])
        except Exception as e: print("daily error", e)
        time.sleep(60)

class H(BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
    def log_message(self, *a): pass

def main():
    threading.Thread(target=daily_loop, daemon=True).start()
    if os.environ.get("PORT"):
        threading.Thread(target=HTTPServer(("", int(os.environ["PORT"])), H).serve_forever, daemon=True).start()
    offset = 0
    while True:
        try:
            r = call("getUpdates", offset=offset, timeout=50)
            for u in r.get("result", []):
                offset = u["update_id"] + 1
                if "message" in u: handle(u["message"])
        except Exception as e:
            print("poll error", e); time.sleep(5)

if __name__ == "__main__": main()
