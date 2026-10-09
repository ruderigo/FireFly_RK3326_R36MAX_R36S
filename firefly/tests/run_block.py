"""Delete and block, over a real LXMF link and on screen.

Phase 1: talk to Bob, block him: his replies and announces (every 3 s) are
ignored and he doesn't come back. Phase 2 (a fresh FireFly process on the same
data, i.e. after a restart): still blocked, in LXMF's own ignore list too;
unblock, and he's back. Then the screens: delete one voice note (its audio
files go), delete a conversation from inside it (the chat closes), Cancel is
the default.   python3 tests/run_block.py"""
import os, subprocess, sys, tempfile, time
os.environ.setdefault("SDL_VIDEODRIVER", "dummy"); os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(here, ".."))

def wait(fn, secs):
    t = time.time()
    while time.time() - t < secs:
        if fn(): return True
        time.sleep(0.3)
    return False

def phase(n, home, bob, port):
    from firefly.paths import Paths
    from firefly.settings import Settings
    from firefly.core import Core
    ok = True
    def check(c, w):
        nonlocal ok
        print(("  PASS " if c else "  FAIL ") + w, flush=True); ok = ok and bool(c)
    paths = Paths(home); paths.ensure()
    s = Settings(paths.settings); s["radio"]["enabled"] = False; s["auto_interface"] = False
    s["share_instance"] = False; s["tcp_peers"] = [f"127.0.0.1:{port}"]; s["log_level"] = 2; s.save()
    core = Core(paths, log=lambda *a: None); core.start()
    if n == 1:
        check(wait(lambda: (core.store.peer(bob) or {}).get("name"), 20), "Bob heard")
        core.send(bob, "hello")
        check(wait(lambda: any(not m["outgoing"] for m in core.store.messages(bob)), 30), "Bob's reply arrives")
        core.block(bob)
        check(not core.store.messages(bob) and core.store.peer(bob) is None, "block deletes the conversation and the contact")
        check(bytes.fromhex(bob) in core.router.ignored_list, "Bob is in LXMF's own ignore list")
        core.send(bob, "are you there?")               # he will reply: that reply must be ignored
        time.sleep(12)                                 # several of his 3 s announces, and his reply
        check(core.store.peer(bob) is None, "his announces are ignored: he doesn't reappear")
        check(not any(not m["outgoing"] for m in core.store.messages(bob)), "his reply was ignored")
    else:
        check(core.is_blocked(bob) and bytes.fromhex(bob) in core.router.ignored_list,
              "after a restart: still blocked, and back in LXMF's ignore list")
        try:
            core.add_contact(bob); check(False, "adding a blocked address is refused")
        except ValueError as e:
            check("blocked" in str(e), f"adding a blocked address is refused ('{e}')")
        time.sleep(6)
        check(core.store.peer(bob) is None, "still ignored after the restart")
        core.unblock(bob)
        check(wait(lambda: core.store.peer(bob) is not None, 20), "unblocked: his next announce brings him back")
        core.send(bob, "welcome back")
        check(wait(lambda: any(not m["outgoing"] for m in core.store.messages(bob)), 30), "and his replies arrive again")
    core.stop()
    print("PHASE OK" if ok else "PHASE FAILED", flush=True)
    os._exit(0 if ok else 1)

def screens():
    from firefly.paths import Paths
    from firefly.settings import Settings
    from firefly.core import Core
    from firefly import voice
    import LXMF
    ok = True
    def check(c, w):
        nonlocal ok
        print(("  PASS " if c else "  FAIL ") + w, flush=True); ok = ok and bool(c)
    t = tempfile.mkdtemp(); paths = Paths(t); paths.ensure()
    s = Settings(paths.settings); s["radio"]["enabled"] = False; s["auto_interface"] = False; s["share_instance"] = False; s.save()
    core = Core(paths, log=lambda *a: None); core.start()
    bob, ann = "823de26f44824bc5d37611af7851414c", "a8e7c0e088fc474c34360e91059be857"
    core.store.upsert_peer(bob, "lxmf", name="Bob"); core.store.upsert_peer(ann, "lxmf", name="Ann")
    vec = open(os.path.join(here, "data", "kristoff_1200.bit"), "rb").read()
    path = voice.save(paths.audio, "n1", LXMF.AM_CODEC2_1200, vec)
    voice.decode_to_wav(path, LXMF.AM_CODEC2_1200)
    core.store.add_message(bob, False, "first", "received")
    note = core.store.add_message(bob, False, "", "received", audio_mode=LXMF.AM_CODEC2_1200, audio_path=path, audio_secs=5.0)
    core.store.add_message(bob, True, "last", "delivered")
    core.store.add_message(ann, False, "hi from Ann", "received")
    from firefly.ui.app import App
    from firefly.ui.screens import ChatScreen
    app = App(core, size=(640, 480))
    chat = ChatScreen(app, bob); app.push(chat)
    app.action("up")                                   # select the voice note
    check(chat._selected(chat._messages())["id"] == note, "voice note selected")
    app.action("y")
    labels = [l for l, _ in app.current.items]
    check("Delete the selected message" in labels and "Block" in labels and labels[-1] == "Block",
          "chat menu: delete the selected message, delete conversation, block (destructive ones last)")
    app.current.sel = labels.index("Delete the selected message"); app.action("a")
    check([l for l, _ in app.current.items][0] == "Cancel" and app.current.sel == 0, "confirmation opens on Cancel")
    app.action("a")                                    # Cancel
    check(core.store.message(note) is not None, "Cancel deletes nothing")
    app.action("y"); app.current.sel = [l for l, _ in app.current.items].index("Delete the selected message"); app.action("a")
    app.action("down"); app.action("a")                # Delete
    check(core.store.message(note) is None, "the voice note is deleted")
    check(not os.path.exists(path) and not os.path.exists(path + ".wav"), "  ...and its audio files with it")
    check(chat._selected(chat._messages())["content"] == "first", "selection moves to the neighbouring message")
    app.render()
    app.action("y"); app.current.sel = [l for l, _ in app.current.items].index("Delete conversation and contact"); app.action("a")
    app.action("down"); app.action("a")
    check(not core.store.messages(bob) and core.store.peer(bob) is None, "conversation and contact deleted")
    check(not any(isinstance(sc, ChatScreen) for sc in app.stack), "the chat closes")
    check(core.store.peer(ann) is not None and core.store.messages(ann), "other conversations untouched")
    app.switch_tab(1); tab = app.tabs[1]
    rows = tab.rows(); tab.sel = next(i for i, r in enumerate(rows) if r.get("hash") == ann)
    app.action("y"); app.current.sel = [l for l, _ in app.current.items].index("Block"); app.action("a")
    app.action("down"); app.action("a")
    check(core.is_blocked(ann) and core.store.peer(ann) is None, "blocked from the PEERS tab")
    app.switch_tab(3); st = app.tabs[3]
    st.sel = [r[0] for r in st.rows()].index("blocked"); app.render()
    check(dict((r[0], r[2]) for r in st.rows())["blocked"] == "1", "SETUP shows 1 blocked")
    app.action("a"); check("Unblock Ann" in app.current.items[0][0], "SETUP > Blocked lists Ann by name")
    app.action("a"); check(not core.is_blocked(ann), "unblocked from SETUP")
    core.stop()
    print("PHASE OK" if ok else "PHASE FAILED", flush=True)
    os._exit(0 if ok else 1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--phase":
        phase(int(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5]))
    if len(sys.argv) > 1 and sys.argv[1] == "--screens":
        screens()
    tmp = tempfile.mkdtemp(); port = 47901
    peer = subprocess.Popen([sys.executable, "-u", os.path.join(here, "peer.py"), os.path.join(tmp, "bob"), str(port)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    line = peer.stdout.readline()
    while "PEER ready" not in line: line = peer.stdout.readline()
    bob = line.split()[2]
    home = os.path.join(tmp, "me"); results = []
    for n in (1, 2):
        print(f"-- {'talk, then block' if n == 1 else 'after a restart'}", flush=True)
        r = subprocess.run([sys.executable, "-u", __file__, "--phase", str(n), home, bob, str(port)])
        results.append(r.returncode == 0)
    peer.terminate()
    print("-- screens", flush=True)
    results.append(subprocess.run([sys.executable, "-u", __file__, "--screens"]).returncode == 0)
    print("ALL PASSED" if all(results) else "SOME FAILED")
