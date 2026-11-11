"""Live TV channel controls: add / edit / delete / enable-disable.

Every test runs against a TEMP registry (the real shape, a few
channels). No test touches a live registry, spawns a real probe, or
prints a credential. The stream checker is always injected."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from admin_v2.errors import ApiError  # noqa: E402
from admin_v2.live_stores import LiveStores, check_stream_url  # noqa: E402
from admin_v2.services import Service  # noqa: E402


def alive_checker(url):
    return {"alive": True, "status": 200, "error": None}


def dead_checker(url):
    return {"alive": False, "status": 0, "error": "boom"}


def _ch(cid, name, stream, source="official", enabled=True, reason=""):
    return {"id": cid, "name": name, "category": "news", "country": "PK",
            "language": "ur", "logo_url": "",
            "stream_url": stream, "source": source, "verified_at": "",
            "enabled": enabled, "disabled_reason": reason}


REGISTRY = {
    "version": 1, "source": "test", "note": "test registry",
    "updated_at": "2026-11-11T00:00:00Z",
    "channels": [
        _ch(1, "Dunya News", "https://example.com/dunya.m3u8"),
        _ch(2, "24 News HD", "https://example.com/24.m3u8",
            source="aggregator", enabled=False, reason="third-party restream"),
        _ch(3, "Hum TV", "https://example.com/hum.m3u8",
            source="aggregator", enabled=False, reason="third-party restream"),
    ],
}

# The 18 restream ids the owner ordered dropped (2026-11-11). The
# removal test builds a 35-channel registry from these + the 17
# official ids and deletes exactly these, proving only the 17 stay.
RESTREAM_IDS = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 15, 17, 20, 24, 25, 31, 34]
OFFICIAL_IDS = [1, 11, 14, 16, 18, 19, 21, 22, 23, 26, 27, 28, 29, 30, 32, 33, 35]


class LiveTvBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="livetv-test-")
        self.fleet_dir = os.path.join(self.tmp, "fleet")
        os.makedirs(self.fleet_dir)
        self.registry_path = os.path.join(self.fleet_dir, "live_tv_registry.json")
        with open(self.registry_path, "w", encoding="utf-8") as fh:
            json.dump(REGISTRY, fh, indent=2)
        self.live = LiveStores(fleet_base_dir=self.fleet_dir)
        self.admin_dir = os.path.join(self.tmp, "admin")
        self.svc = Service(self.admin_dir, live=self.live)
        self.owner_id = self.svc.create_owner("owner", "correct horse battery staple")
        self.owner = {"id": self.owner_id, "username": "owner", "role": "owner"}
        self.auditor = {"id": 999, "username": "auditor", "role": "auditor"}

    def _registry(self):
        with open(self.registry_path, encoding="utf-8") as fh:
            return json.load(fh)

    def _channels(self):
        return self.svc.list_live_tv(self.owner)["channels"]

    def _by_id(self, cid):
        for c in self._channels():
            if c["id"] == cid:
                return c
        return None


class TestAddChannel(LiveTvBase):
    def test_add_alive_stream_succeeds_with_next_id(self):
        res = self.svc.add_live_tv_channel(
            self.owner, {"name": "New Channel", "category": "news",
                         "country": "PK", "language": "ur",
                         "stream_url": "https://example.com/new.m3u8"},
            checker=alive_checker)
        self.assertEqual(res["channel"]["id"], 4)
        self.assertEqual(res["channel"]["name"], "New Channel")
        self.assertTrue(res["channel"]["enabled"])
        self.assertEqual(res["warnings"], [])
        self.assertTrue(res["channel"]["verified_at"])
        self.assertEqual(len(self._channels()), 4)
        # Written to disk, top-level keys preserved.
        data = self._registry()
        self.assertEqual(sorted(data.keys()),
                         sorted(["version", "source", "note", "updated_at", "channels"]))
        self.assertEqual(data["channels"][-1]["name"], "New Channel")

    def test_add_dead_stream_refuses_without_force(self):
        with self.assertRaises(ApiError):
            self.svc.add_live_tv_channel(
                self.owner, {"name": "Dead Channel",
                             "stream_url": "https://example.com/dead.m3u8"},
                checker=dead_checker)
        self.assertEqual(len(self._channels()), 3)

    def test_add_dead_stream_with_force_succeeds_with_warning(self):
        res = self.svc.add_live_tv_channel(
            self.owner, {"name": "Dead Channel",
                         "stream_url": "https://example.com/dead.m3u8",
                         "force": True},
            checker=dead_checker)
        self.assertEqual(res["channel"]["name"], "Dead Channel")
        self.assertTrue(any("did not answer" in w for w in res["warnings"]))
        self.assertEqual(res["channel"]["verified_at"], "")

    def test_add_duplicate_name_warns_but_succeeds(self):
        res = self.svc.add_live_tv_channel(
            self.owner, {"name": "dunya news",
                         "stream_url": "https://example.com/other.m3u8"},
            checker=alive_checker)
        self.assertTrue(any("already exists" in w for w in res["warnings"]))
        self.assertEqual(len(self._channels()), 4)

    def test_add_duplicate_stream_url_warns_but_succeeds(self):
        res = self.svc.add_live_tv_channel(
            self.owner, {"name": "Another",
                         "stream_url": "https://example.com/dunya.m3u8"},
            checker=alive_checker)
        self.assertTrue(any("already used" in w for w in res["warnings"]))

    def test_add_missing_name_or_bad_url_refuses(self):
        with self.assertRaises(ApiError):
            self.svc.add_live_tv_channel(
                self.owner, {"stream_url": "https://example.com/x.m3u8"},
                checker=alive_checker)
        with self.assertRaises(ApiError):
            self.svc.add_live_tv_channel(
                self.owner, {"name": "X", "stream_url": "ftp://example.com/x"},
                checker=alive_checker)
        with self.assertRaises(ApiError):
            self.svc.add_live_tv_channel(
                self.owner, {"name": "X", "stream_url": "not-a-url"},
                checker=alive_checker)

    def test_add_rejects_bad_source(self):
        with self.assertRaises(ApiError):
            self.svc.add_live_tv_channel(
                self.owner, {"name": "X",
                             "stream_url": "https://example.com/x.m3u8",
                             "source": "pirate"},
                checker=alive_checker)

    def test_add_forbidden_for_auditor(self):
        with self.assertRaises(ApiError):
            self.svc.add_live_tv_channel(
                self.auditor, {"name": "X",
                               "stream_url": "https://example.com/x.m3u8"},
                checker=alive_checker)

    def test_add_disabled_channel_keeps_reason(self):
        res = self.svc.add_live_tv_channel(
            self.owner, {"name": "Off Air",
                         "stream_url": "https://example.com/off.m3u8",
                         "enabled": "0"},
            checker=alive_checker)
        self.assertFalse(res["channel"]["enabled"])
        self.assertEqual(res["channel"]["disabled_reason"], "disabled from panel")


class TestUpdateChannel(LiveTvBase):
    def test_update_changes_only_given_fields(self):
        res = self.svc.update_live_tv_channel(
            self.owner, 1, {"name": "Dunya News HD",
                            "category": "news"},
            checker=alive_checker)
        self.assertEqual(res["channel"]["name"], "Dunya News HD")
        self.assertEqual(res["channel"]["stream_url"],
                         "https://example.com/dunya.m3u8")
        self.assertEqual(res["channel"]["country"], "PK")
        self.assertEqual(res["warnings"], [])

    def test_update_stream_url_probes_the_new_url(self):
        res = self.svc.update_live_tv_channel(
            self.owner, 1,
            {"stream_url": "https://example.com/dunya2.m3u8"},
            checker=alive_checker)
        self.assertEqual(res["channel"]["stream_url"],
                         "https://example.com/dunya2.m3u8")
        self.assertTrue(res["channel"]["verified_at"])

    def test_update_dead_stream_refuses_without_force(self):
        with self.assertRaises(ApiError):
            self.svc.update_live_tv_channel(
                self.owner, 1,
                {"stream_url": "https://example.com/dead.m3u8"},
                checker=dead_checker)
        self.assertEqual(self._by_id(1)["stream_url"],
                         "https://example.com/dunya.m3u8")

    def test_update_dead_stream_with_force_succeeds(self):
        res = self.svc.update_live_tv_channel(
            self.owner, 1,
            {"stream_url": "https://example.com/dead.m3u8", "force": "1"},
            checker=dead_checker)
        self.assertEqual(res["channel"]["stream_url"],
                         "https://example.com/dead.m3u8")
        self.assertTrue(any("did not answer" in w for w in res["warnings"]))

    def test_update_duplicate_name_warns(self):
        res = self.svc.update_live_tv_channel(
            self.owner, 1, {"name": "Hum TV"}, checker=alive_checker)
        self.assertTrue(any("already exists" in w for w in res["warnings"]))

    def test_update_missing_channel_not_found(self):
        with self.assertRaises(ApiError):
            self.svc.update_live_tv_channel(
                self.owner, 999, {"name": "Ghost"}, checker=alive_checker)

    def test_update_enabling_clears_disabled_reason(self):
        res = self.svc.update_live_tv_channel(
            self.owner, 2, {"enabled": "1"}, checker=alive_checker)
        self.assertTrue(res["channel"]["enabled"])
        self.assertEqual(res["channel"]["disabled_reason"], "")

    def test_update_forbidden_for_auditor(self):
        with self.assertRaises(ApiError):
            self.svc.update_live_tv_channel(
                self.auditor, 1, {"name": "X"}, checker=alive_checker)


class TestDeleteChannel(LiveTvBase):
    def test_delete_removes_the_channel(self):
        res = self.svc.delete_live_tv_channel(
            self.owner, 2, {"confirm": True})
        self.assertTrue(res["deleted"])
        self.assertEqual(res["id"], 2)
        self.assertEqual(res["name"], "24 News HD")
        self.assertIsNone(self._by_id(2))
        self.assertEqual(len(self._channels()), 2)
        self.assertEqual([c["id"] for c in self._registry()["channels"]], [1, 3])

    def test_delete_without_confirm_refuses(self):
        with self.assertRaises(ApiError):
            self.svc.delete_live_tv_channel(self.owner, 2, {})
        with self.assertRaises(ApiError):
            self.svc.delete_live_tv_channel(self.owner, 2, {"confirm": False})
        self.assertIsNotNone(self._by_id(2))

    def test_delete_missing_channel_not_found(self):
        with self.assertRaises(ApiError):
            self.svc.delete_live_tv_channel(self.owner, 999, {"confirm": True})

    def test_delete_forbidden_for_auditor(self):
        with self.assertRaises(ApiError):
            self.svc.delete_live_tv_channel(
                self.auditor, 2, {"confirm": True})

    def test_delete_writes_a_backup_first(self):
        self.svc.delete_live_tv_channel(self.owner, 2, {"confirm": True})
        import glob
        backups = glob.glob(self.registry_path + ".bak-*")
        self.assertEqual(len(backups), 1)
        with open(backups[0], encoding="utf-8") as fh:
            self.assertEqual(len(json.load(fh)["channels"]), 3)


class TestToggleFix(LiveTvBase):
    def test_disable_via_form_string_zero_actually_disables(self):
        # Regression: bool("0") is True, so the HTML toggle form's
        # hidden enabled="0" used to never disable a channel.
        res = self.svc.set_live_tv_channel(
            self.owner, 1, {"enabled": "0", "reason": "off air"})
        self.assertFalse(res["enabled"])
        self.assertFalse(self._by_id(1)["enabled"])

    def test_enable_via_form_string_one_enables(self):
        res = self.svc.set_live_tv_channel(self.owner, 2, {"enabled": "1"})
        self.assertTrue(res["enabled"])
        self.assertTrue(self._by_id(2)["enabled"])
        self.assertEqual(self._by_id(2)["disabled_reason"], "")


class TestListAndRemoval(LiveTvBase):
    def test_list_returns_stream_url_logo_and_source(self):
        ch = self._by_id(1)
        self.assertEqual(ch["stream_url"], "https://example.com/dunya.m3u8")
        self.assertEqual(ch["source"], "official")

    def test_drop_eighteen_restream_ids_leaves_seventeen(self):
        # The exact operation the owner ordered on the live registry:
        # build the real 35-channel shape, delete the 18 restreams.
        channels = []
        for cid in OFFICIAL_IDS:
            channels.append(_ch(cid, "Official %d" % cid,
                                "https://example.com/o%d.m3u8" % cid))
        for cid in RESTREAM_IDS:
            channels.append(_ch(cid, "Restream %d" % cid,
                                "https://example.com/r%d.m3u8" % cid,
                                source="aggregator", enabled=False,
                                reason="third-party restream"))
        with open(self.registry_path, "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "source": "test", "note": "",
                       "updated_at": "", "channels": channels}, fh)
        self.assertEqual(len(self._channels()), 35)
        for cid in RESTREAM_IDS:
            self.svc.delete_live_tv_channel(
                self.owner, cid, {"confirm": True})
        remaining = self._channels()
        self.assertEqual(len(remaining), 17)
        self.assertEqual(sorted(c["id"] for c in remaining), OFFICIAL_IDS)
        self.assertTrue(all(c["enabled"] for c in remaining))


class TestCheckStreamUrl(unittest.TestCase):
    def test_rejects_empty_and_non_http_urls_without_network(self):
        self.assertFalse(check_stream_url("")["alive"])
        self.assertFalse(check_stream_url("ftp://example.com/x")["alive"])
        self.assertFalse(check_stream_url(None)["alive"])


if __name__ == "__main__":
    unittest.main()
