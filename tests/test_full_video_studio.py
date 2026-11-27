import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import luna.app as app_module
from luna import ffmpeg_setup, studio_service


class TestFullVideoStudio(unittest.TestCase):
    def test_studio_mode_classification(self):
        self.assertEqual(
            studio_service.get_studio_mode({
                "project_id": "p1",
                "action": "type_yt_ai_clip",
                "files": [{"id": "f1", "type": "video", "filename": "clip_1.mp4"}],
            }),
            "ai_clip",
        )
        self.assertEqual(
            studio_service.get_studio_mode({
                "project_id": "p2",
                "action": "type_yt_video",
                "files": [{"id": "f1", "type": "video", "filename": "full.mp4"}],
            }),
            "full_video",
        )
        self.assertEqual(
            studio_service.get_studio_mode({
                "project_id": "p3",
                "action": "type_ig_reels",
                "files": [{"id": "f1", "type": "video", "filename": "reel.mp4"}],
            }),
            "full_video",
        )
        # Audio-only and Video Trimmer stay excluded from v1.3.0 Studio
        self.assertIsNone(
            studio_service.get_studio_mode({
                "project_id": "p4",
                "action": "type_yt_mp3",
                "files": [{"id": "f1", "type": "audio", "filename": "song.mp3"}],
            })
        )
        self.assertIsNone(
            studio_service.get_studio_mode({
                "project_id": "p5",
                "action": "type_yt_clip",
                "files": [{"id": "f1", "type": "video", "filename": "trim.mp4"}],
            })
        )

    def test_segments_curve_atempo_crop_and_color_helpers(self):
        # 5-point 2D speed curve interpolation (default + custom shifted X positions)
        dip = [1.4, 0.9, 0.4, 0.9, 1.4]
        self.assertAlmostEqual(studio_service._sample_curve_speed(dip, 0.0), 1.4, places=2)
        self.assertAlmostEqual(studio_service._sample_curve_speed(dip, 0.5), 0.4, places=2)
        self.assertAlmostEqual(studio_service._sample_curve_speed(dip, 1.0), 1.4, places=2)
        shifted_pos = studio_service._sanitize_curve_positions([0.0, 0.15, 0.30, 0.80, 1.0])
        self.assertEqual(shifted_pos, [0.0, 0.15, 0.3, 0.8, 1.0])
        self.assertAlmostEqual(studio_service._sample_curve_speed(dip, 0.30, shifted_pos), 0.4, places=2)
        self.assertAlmostEqual(studio_service._sample_curve_speed(dip, 0.80, shifted_pos), 0.9, places=2)

        # Normal + curve segment expansion
        segs = studio_service._sanitize_segments(
            [
                {
                    "id": "seg_1",
                    "sourceStart": 0.0,
                    "sourceEnd": 4.0,
                    "volume": 80,
                    "speedMode": "normal",
                    "speed": 1.5,
                    "curvePreset": "none",
                    "curvePoints": [1.0, 1.0, 1.0, 1.0, 1.0],
                },
                {
                    "id": "seg_2",
                    "sourceStart": 8.0,
                    "sourceEnd": 12.0,
                    "volume": 100,
                    "speedMode": "curve",
                    "speed": 1.0,
                    "curvePreset": "dip",
                    "curvePoints": dip,
                },
            ],
            20.0,
        )
        self.assertEqual(len(segs), 2)
        pieces = studio_service._expand_segments_to_pieces(segs)
        self.assertEqual(pieces[0], (0.0, 4.0, 1.5, 0.8, 50.0, 50.0))
        # Second segment expands into 8 smooth curve sub-pieces spanning [8.0, 12.0]
        curve_pieces = pieces[1:]
        self.assertGreaterEqual(len(curve_pieces), 4)
        self.assertAlmostEqual(curve_pieces[0][0], 8.0, places=2)
        self.assertAlmostEqual(curve_pieces[-1][1], 12.0, places=2)
        self.assertTrue(any(p[2] < 0.7 for p in curve_pieces))

        # Flat curve collapses into a single atomic piece
        flat_pieces = studio_service._expand_segments_to_pieces([
            {
                "id": "seg_flat",
                "sourceStart": 0.0,
                "sourceEnd": 5.0,
                "volume": 100,
                "speedMode": "curve",
                "speed": 1.0,
                "curvePreset": "none",
                "curvePoints": [1.0, 1.0, 1.0, 1.0, 1.0],
                "cropX": 20.0,
                "cropY": 50.0,
            }
        ])
        self.assertEqual(flat_pieces, [(0.0, 5.0, 1.0, 1.0, 20.0, 50.0)])

        self.assertEqual(studio_service._atempo_chain(0.25), "atempo=0.5000,atempo=0.5000")
        self.assertEqual(studio_service._atempo_chain(4.0), "atempo=2.0000,atempo=2.0000")
        self.assertEqual(studio_service._atempo_chain(1.5), "atempo=1.5000")
        self.assertEqual(studio_service._atempo_chain(1.0), "")

        self.assertEqual(
            studio_service._build_crop_filter("1:1", 1920, 1080),
            "crop=1080:1080:(iw-1080)/2:(ih-1080)/2",
        )
        self.assertEqual(
            studio_service._build_crop_filter("1:1", 1920, 1080, crop_x=0.0, crop_y=50.0),
            "crop=1080:1080:0:0",
        )
        self.assertEqual(
            studio_service._build_crop_filter("1:1", 1920, 1080, crop_x=100.0, crop_y=50.0),
            "crop=1080:1080:840:0",
        )
        self.assertEqual(
            studio_service._build_crop_filter("1:1", 1080, 1920, crop_x=50.0, crop_y=25.0),
            "crop=1080:1080:0:210",
        )
        self.assertIsNone(studio_service._build_crop_filter("original", 1920, 1080))

        warm_filters = studio_service._build_color_filters(
            {"preset": "warm", "brightness": 4, "contrast": 6, "saturation": 12}
        )
        self.assertTrue(any(f.startswith("eq=") for f in warm_filters))
        self.assertTrue(any("lutyuv=" in f for f in warm_filters))
        self.assertFalse(any("colorbalance=" in f for f in warm_filters))

        bw_filters = studio_service._build_color_filters(
            {"preset": "bw", "brightness": 0, "contrast": 14, "saturation": -50}
        )
        self.assertEqual(len(bw_filters), 1)
        self.assertIn("saturation=0.000", bw_filters[0])

        # Extended Adjust filters: exposure (gamma), pure-YUV warmth (lutyuv), fast 3x3 unsharp, vignette
        cine_filters = studio_service._build_color_filters(
            {
                "preset": "cinematic",
                "brightness": -4,
                "exposure": 10,
                "contrast": 16,
                "saturation": -8,
                "warmth": -12,
                "sharpness": 18,
                "vignette": 25,
            }
        )
        self.assertTrue(any("gamma=" in f for f in cine_filters))
        self.assertTrue(any("lutyuv=" in f for f in cine_filters))
        self.assertFalse(any("colorbalance=" in f for f in cine_filters))
        self.assertTrue(any(f.startswith("unsharp=3:3:") for f in cine_filters))
        self.assertTrue(any(f.startswith("vignette=") for f in cine_filters))

    def test_full_video_studio_blocks_curve_export_and_extract_e2e(self):
        if not ffmpeg_setup.ensure_ffmpeg():
            self.skipTest("FFmpeg is required for live render E2E test")

        with tempfile.TemporaryDirectory() as tmp:
            proj_dir = Path(tmp) / "02-Full-Video" / "Sample Full Video"
            proj_dir.mkdir(parents=True)
            vid_path = proj_dir / "sample_video.mp4"

            # Generate a tiny 4-second 320x180 MP4 with audio
            gen = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-f",
                    "lavfi",
                    "-i",
                    "testsrc=duration=4:size=320x180:rate=24",
                    "-f",
                    "lavfi",
                    "-i",
                    "sine=frequency=440:duration=4",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    str(vid_path),
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(gen.returncode, 0, gen.stderr)

            fake_proj = {
                "project_id": "proj_fv_test",
                "workspace_name": "Sample Full Video",
                "action": "type_yt_video",
                "category": "02-Full-Video",
                "folder_path": str(proj_dir),
                "files": [
                    {
                        "id": "vid_01",
                        "title": "Sample Full Video",
                        "filename": "sample_video.mp4",
                        "file_path": str(vid_path),
                        "type": "video",
                        "action": "type_yt_video",
                    }
                ],
            }

            with patch.object(studio_service.storage_manager, "get_storage_root", return_value=tmp), \
                    patch.object(studio_service.vault_service, "list_vault_projects", return_value=[fake_proj]):
                client = TestClient(app_module.app, base_url="http://127.0.0.1:8000")

                # 1. Load project API reports full_video mode with 1 default segment
                r_load = client.get("/api/studio/proj_fv_test")
                self.assertEqual(r_load.status_code, 200)
                loaded = r_load.json()
                self.assertEqual(loaded["mode"], "full_video")
                self.assertEqual(len(loaded["clips"]), 1)
                self.assertEqual(len(loaded["clips"][0]["segments"]), 1)

                # 2. Save Full Video draft (2 ripple-deleted blocks + 5-point speed curve + crop + color + fade)
                draft_clip = {
                    "id": "vid_01",
                    "dur": 4.0,
                    "start": 0.0,
                    "end": 4.0,
                    "cropRatio": "1:1",
                    "fade": 0.5,
                    "color": {"preset": "warm", "brightness": 4, "contrast": 6, "saturation": 12},
                    "segments": [
                        {
                            "id": "seg_1",
                            "sourceStart": 0.0,
                            "sourceEnd": 1.6,
                            "volume": 80,
                            "speedMode": "curve",
                            "speed": 1.0,
                            "curvePreset": "dip",
                            "curvePoints": [1.4, 0.9, 0.4, 0.9, 1.4],
                            "cropX": 15.0,
                            "cropY": 50.0,
                        },
                        {
                            "id": "seg_2",
                            "sourceStart": 2.4,
                            "sourceEnd": 4.0,
                            "volume": 100,
                            "speedMode": "normal",
                            "speed": 1.5,
                            "curvePreset": "none",
                            "curvePoints": [1.0, 1.0, 1.0, 1.0, 1.0],
                            "cropX": 85.0,
                            "cropY": 50.0,
                        },
                    ],
                }
                r_save = client.post("/api/studio/proj_fv_test/save", json={"clips": [draft_clip]})
                self.assertEqual(r_save.status_code, 200)
                reloaded = client.get("/api/studio/proj_fv_test").json()["clips"][0]
                self.assertEqual(reloaded["cropRatio"], "1:1")
                self.assertEqual(len(reloaded["segments"]), 2)
                self.assertEqual(reloaded["segments"][0]["volume"], 80)
                self.assertEqual(reloaded["segments"][0]["speedMode"], "curve")
                self.assertEqual(reloaded["segments"][0]["curvePreset"], "dip")
                self.assertEqual(reloaded["segments"][0]["curvePoints"], [1.4, 0.9, 0.4, 0.9, 1.4])
                self.assertEqual(reloaded["segments"][0]["cropX"], 15.0)
                self.assertEqual(reloaded["segments"][1]["cropX"], 85.0)
                self.assertEqual(reloaded["segments"][1]["speed"], 1.5)

                # 3. Tier-1 Fast Lossless export (-c copy)
                r_fast = client.post(
                    "/api/studio/proj_fv_test/export/vid_01",
                    json={
                        "start": 0.0,
                        "end": 3.0,
                        "cropRatio": "original",
                        "fade": 0,
                        "segments": [
                            {
                                "id": "seg_1",
                                "sourceStart": 0.0,
                                "sourceEnd": 3.0,
                                "volume": 100,
                                "speedMode": "normal",
                                "speed": 1.0,
                                "curvePreset": "none",
                                "curvePoints": [1.0, 1.0, 1.0, 1.0, 1.0],
                            }
                        ],
                    },
                )
                self.assertEqual(r_fast.status_code, 200, r_fast.text)
                self.assertEqual(r_fast.headers["content-type"], "video/mp4")
                self.assertGreater(len(r_fast.content), 1000)

                # 4. Tier-3 Smart Render (Multi-block ripple cut + Speed Curve + 1:1 Crop + Color + Fade)
                r_fx = client.post(
                    "/api/studio/proj_fv_test/export/vid_01",
                    json=draft_clip,
                )
                self.assertEqual(r_fx.status_code, 200, r_fx.text)
                exported_mp4 = proj_dir / studio_service.STUDIO_EXPORTS_DIR / "sample_video_studio.mp4"
                self.assertTrue(exported_mp4.is_file())
                _, w, h = studio_service._probe_video_info(str(exported_mp4))
                self.assertEqual(w, h)  # 1:1 square crop verified

                # 5. Extract MP3 endpoint (honors multi-block segments + curve audio tempo)
                r_mp3 = client.post(
                    "/api/studio/proj_fv_test/extract-audio/vid_01",
                    json=draft_clip,
                )
                self.assertEqual(r_mp3.status_code, 200, r_mp3.text)
                self.assertEqual(r_mp3.headers["content-type"], "audio/mpeg")
                self.assertGreater(len(r_mp3.content), 1000)

                # 6. Removed snapshot endpoint returns 404
                r_snap = client.post("/api/studio/proj_fv_test/snapshot/vid_01", json={"time": 1.0})
                self.assertEqual(r_snap.status_code, 404)

                # 7. Music upload probes real audio duration & load_studio_project heals inflated totalDur
                short_wav = Path(tmp) / "short_bgm.wav"
                res_wav = subprocess.run(
                    [
                        "ffmpeg",
                        "-y",
                        "-f",
                        "lavfi",
                        "-i",
                        "sine=frequency=440:duration=1.5",
                        str(short_wav),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(res_wav.returncode, 0, res_wav.stderr)
                r_up = client.post(
                    "/api/studio/proj_fv_test/music?clip_id=vid_01&filename=short_bgm.wav",
                    content=short_wav.read_bytes(),
                    headers={"Content-Type": "application/octet-stream"},
                )
                self.assertEqual(r_up.status_code, 200, r_up.text)
                up_data = r_up.json()
                self.assertAlmostEqual(up_data["duration"], 1.5, delta=0.15)

                # Simulate an old corrupted draft where totalDur was inflated to 1731s (video length)
                corrupted_clip = {
                    **draft_clip,
                    "music": {
                        "name": "short_bgm.wav",
                        "assetName": up_data["assetName"],
                        "totalDur": 1731.0,
                        "sliceStart": 120.0,
                        "volume": 35,
                        "peaks": [0.2, 0.5, 0.8],
                    },
                }
                r_save_corrupt = client.post("/api/studio/proj_fv_test/save", json={"clips": [corrupted_clip]})
                self.assertEqual(r_save_corrupt.status_code, 200)
                healed = client.get("/api/studio/proj_fv_test").json()["clips"][0]["music"]
                self.assertAlmostEqual(healed["totalDur"], 1.5, delta=0.15)
                self.assertLess(healed["sliceStart"], 1.5)

                # Slice resolution: 0.0 when music <= target_dur; preserved/clamped when music > target_dur
                asset_disk = studio_service.get_studio_music_path("proj_fv_test", up_data["assetName"])
                self.assertIsNotNone(asset_disk)
                self.assertEqual(studio_service._resolve_music_slice_start(asset_disk, 0.8, 3.0), 0.0)
                self.assertAlmostEqual(
                    studio_service._resolve_music_slice_start(asset_disk, 0.4, 0.6), 0.4, delta=0.05
                )

                # 8. Auto-migration from legacy clip.music -> proportional audioClips[] (never stretched to video dur)
                reloaded_mig = client.get("/api/studio/proj_fv_test").json()["clips"][0]
                self.assertEqual(len(reloaded_mig["audioClips"]), 1)
                mig_ac = reloaded_mig["audioClips"][0]
                self.assertAlmostEqual(mig_ac["sourceDur"], 1.5, delta=0.15)
                self.assertLessEqual(mig_ac["trimEnd"] - mig_ac["trimStart"], 1.65)

                # 9. Multi-block NLE audioClips persistence + FFmpeg Tier-2, Tier-3 & muted MP3 export with fade + keyframes
                nle_audio_clips = [
                    {
                        "id": "aud_a",
                        "name": "short_bgm.wav",
                        "assetName": up_data["assetName"],
                        "sourceDur": 1.5,
                        "timelineStart": 0.2,
                        "trimStart": 0.0,
                        "trimEnd": 1.0,
                        "volume": 45,
                        "fadeIn": 0.2,
                        "fadeOut": 0.2,
                        "keyframes": [
                            {"t": 0.0, "vol": 60},
                            {"t": 0.5, "vol": 15},
                            {"t": 1.0, "vol": 50},
                        ],
                        "peaks": [0.3, 0.7, 0.5],
                    },
                    {
                        "id": "aud_b",
                        "name": "short_bgm.wav",
                        "assetName": up_data["assetName"],
                        "sourceDur": 1.5,
                        "timelineStart": 1.5,
                        "trimStart": 0.2,
                        "trimEnd": 1.2,
                        "volume": 35,
                        "fadeIn": 0.15,
                        "fadeOut": 0.15,
                        "keyframes": [],
                        "peaks": [0.4, 0.6, 0.4],
                    },
                ]
                r_save_nle = client.post(
                    "/api/studio/proj_fv_test/save",
                    json={"clips": [{**draft_clip, "audioClips": nle_audio_clips}]},
                )
                self.assertEqual(r_save_nle.status_code, 200)
                reloaded_nle = client.get("/api/studio/proj_fv_test").json()["clips"][0]["audioClips"]
                self.assertEqual(len(reloaded_nle), 2)
                self.assertAlmostEqual(reloaded_nle[0]["timelineStart"], 0.2, delta=0.01)
                self.assertAlmostEqual(reloaded_nle[0]["fadeIn"], 0.2, delta=0.01)
                self.assertEqual(len(reloaded_nle[0]["keyframes"]), 3)
                self.assertAlmostEqual(reloaded_nle[1]["timelineStart"], 1.5, delta=0.01)

                # Tier-2 Fast Video Copy (-c:v copy) with positioned/faded/keyframed audioClips
                r_t2_audio = client.post(
                    "/api/studio/proj_fv_test/export/vid_01",
                    json={
                        "start": 0.0,
                        "end": 3.0,
                        "cropRatio": "original",
                        "fade": 0,
                        "segments": [
                            {
                                "id": "seg_1",
                                "sourceStart": 0.0,
                                "sourceEnd": 3.0,
                                "volume": 100,
                                "speedMode": "normal",
                                "speed": 1.0,
                                "curvePreset": "none",
                                "curvePoints": [1.0, 1.0, 1.0, 1.0, 1.0],
                            }
                        ],
                        "audioClips": nle_audio_clips,
                    },
                )
                self.assertEqual(r_t2_audio.status_code, 200, r_t2_audio.text)
                self.assertGreater(len(r_t2_audio.content), 1000)

                # Tier-3 Smart Render with multi-block video + 2 NLE audioClips
                r_t3_audio = client.post(
                    "/api/studio/proj_fv_test/export/vid_01",
                    json={**draft_clip, "audioClips": nle_audio_clips},
                )
                self.assertEqual(r_t3_audio.status_code, 200, r_t3_audio.text)
                self.assertGreater(len(r_t3_audio.content), 1000)

                # Muted video + positioned audioClips -> Extract MP3 keeps full timeline duration via anullsrc baseline
                r_mp3_muted = client.post(
                    "/api/studio/proj_fv_test/extract-audio/vid_01",
                    json={
                        "start": 0.0,
                        "end": 3.0,
                        "muted": True,
                        "fade": 0,
                        "segments": [
                            {
                                "id": "seg_1",
                                "sourceStart": 0.0,
                                "sourceEnd": 3.0,
                                "volume": 100,
                                "speedMode": "normal",
                                "speed": 1.0,
                                "curvePreset": "none",
                                "curvePoints": [1.0, 1.0, 1.0, 1.0, 1.0],
                            }
                        ],
                        "audioClips": nle_audio_clips,
                    },
                )
                self.assertEqual(r_mp3_muted.status_code, 200, r_mp3_muted.text)
                self.assertEqual(r_mp3_muted.headers["content-type"], "audio/mpeg")
                self.assertGreater(len(r_mp3_muted.content), 1000)

                # Verify volume expression generator syntax
                vol_expr = studio_service._build_audio_volume_filter(35, nle_audio_clips[0]["keyframes"])
                self.assertIn("eval=frame", vol_expr)
                self.assertIn("if(lte(t,", vol_expr)

                # 10. Upload a video file (.mp4) to /music -> extracts MP3 asset & probes duration
                r_vid_extract = client.post(
                    "/api/studio/proj_fv_test/music?clip_id=vid_01&filename=tiktok_song.mp4",
                    content=vid_path.read_bytes(),
                    headers={"Content-Type": "application/octet-stream"},
                )
                self.assertEqual(r_vid_extract.status_code, 200, r_vid_extract.text)
                vid_ext_data = r_vid_extract.json()
                self.assertTrue(vid_ext_data["extractedFromVideo"])
                self.assertEqual(vid_ext_data["name"], "tiktok_song.mp3")
                self.assertTrue(vid_ext_data["assetName"].endswith(".mp3"))
                self.assertAlmostEqual(vid_ext_data["duration"], 4.0, delta=0.35)
                extracted_disk = studio_service.get_studio_music_path("proj_fv_test", vid_ext_data["assetName"])
                self.assertIsNotNone(extracted_disk)

                # 11. Multi-layer overlapping audioClips (track 0 + track 1) + 2D curvePositions + Extended Adjust live export
                layered_clip = {
                    **draft_clip,
                    "color": {
                        "preset": "cinematic",
                        "brightness": -4,
                        "exposure": 8,
                        "contrast": 14,
                        "saturation": -6,
                        "warmth": -10,
                        "sharpness": 12,
                        "vignette": 20,
                    },
                    "segments": [
                        {
                            **draft_clip["segments"][0],
                            "curvePositions": [0.0, 0.15, 0.35, 0.78, 1.0],
                        },
                        draft_clip["segments"][1],
                    ],
                    "audioClips": [
                        {
                            **nle_audio_clips[0],
                            "id": "aud_layer_0",
                            "track": 0,
                            "timelineStart": 0.2,
                        },
                        {
                            **nle_audio_clips[1],
                            "id": "aud_layer_1",
                            "track": 1,
                            "timelineStart": 0.4,  # Overlaps aud_layer_0 on separate lane
                        },
                    ],
                }
                r_save_layered = client.post("/api/studio/proj_fv_test/save", json={"clips": [layered_clip]})
                self.assertEqual(r_save_layered.status_code, 200)
                reloaded_layered = client.get("/api/studio/proj_fv_test").json()["clips"][0]
                self.assertEqual(reloaded_layered["segments"][0]["curvePositions"], [0.0, 0.15, 0.35, 0.78, 1.0])
                self.assertEqual([a["track"] for a in reloaded_layered["audioClips"]], [0, 1])
                self.assertEqual(reloaded_layered["color"]["preset"], "cinematic")
                self.assertEqual(reloaded_layered["color"]["vignette"], 20)

                r_export_layered = client.post("/api/studio/proj_fv_test/export/vid_01", json=layered_clip)
                self.assertEqual(r_export_layered.status_code, 200, r_export_layered.text)
                self.assertGreater(len(r_export_layered.content), 1000)

                # 12. Export to Workspace saves rendered MP4 into project folder + updates meta.json + thumbnail
                (proj_dir / "meta.json").write_text(
                    __import__("json").dumps([fake_proj], indent=2), encoding="utf-8"
                )
                r_exp_ws = client.post("/api/studio/proj_fv_test/export-workspace/vid_01", json=layered_clip)
                self.assertEqual(r_exp_ws.status_code, 200, r_exp_ws.text)
                ws_data = r_exp_ws.json()
                self.assertTrue(ws_data["ok"])
                exp_file = ws_data["file"]
                self.assertEqual(exp_file["filename"], "sample_video_edited.mp4")
                self.assertTrue(Path(exp_file["file_path"]).is_file())
                self.assertTrue(exp_file.get("edited_in_studio"))
                self.assertEqual(exp_file["aspect_ratio"], "1:1")
                self.assertTrue(exp_file.get("thumbnail", "").startswith("/media-vault/"))

                # Second export increments suffix cleanly without overwriting first export
                r_exp_ws2 = client.post("/api/studio/proj_fv_test/export-workspace/vid_01", json=layered_clip)
                self.assertEqual(r_exp_ws2.status_code, 200, r_exp_ws2.text)
                self.assertEqual(r_exp_ws2.json()["file"]["filename"], "sample_video_edited_2.mp4")

                meta_after = __import__("json").loads((proj_dir / "meta.json").read_text(encoding="utf-8"))
                self.assertEqual(len(meta_after[0]["files"]), 3)

                # 13. Direct MP4 Download prepare=1 -> native attachment stream endpoint
                r_prep = client.post("/api/studio/proj_fv_test/export/vid_01?prepare=1", json=layered_clip)
                self.assertEqual(r_prep.status_code, 200, r_prep.text)
                prep_data = r_prep.json()
                self.assertTrue(prep_data["ok"])
                r_dl = client.get(prep_data["downloadUrl"])
                self.assertEqual(r_dl.status_code, 200)
                self.assertEqual(r_dl.headers["content-type"], "video/mp4")
                self.assertIn("attachment;", r_dl.headers.get("content-disposition", ""))
                self.assertGreater(len(r_dl.content), 1000)

                # 14. /studio/{project_id} SSR renders full_video mode at 0ms (zero AI Clipper flash)
                r_html = client.get("/studio/proj_fv_test")
                self.assertEqual(r_html.status_code, 200)
                self.assertIn('data-studio-mode="full_video"', r_html.text)
                self.assertIn('id="aiRightTabs" class="hidden ', r_html.text)
                self.assertIn('id="fvRightTabs" class=" flat-row', r_html.text)
                self.assertNotIn('id="exportDropdownMenu"', r_html.text)

                # 15. Async Studio Render Job with real-time FFmpeg progress polling
                r_job_start = client.post(
                    "/api/studio/proj_fv_test/jobs/vid_01",
                    json={"mode": "download", "payload": layered_clip},
                )
                self.assertEqual(r_job_start.status_code, 200, r_job_start.text)
                job_id = r_job_start.json()["jobId"]
                job_done = None
                for _ in range(120):
                    r_poll = client.get(f"/api/studio/jobs/{job_id}")
                    self.assertEqual(r_poll.status_code, 200)
                    jd = r_poll.json()
                    if jd["status"] != "running":
                        job_done = jd
                        break
                    __import__("time").sleep(0.1)
                self.assertIsNotNone(job_done)
                self.assertEqual(job_done["status"], "done", job_done)
                self.assertEqual(job_done["progress"], 100)
                self.assertTrue(job_done["downloadUrl"].startswith("/api/studio/proj_fv_test/download-export/"))

                # 16. Cancel endpoint cleanly terminates an active render job
                r_job2 = client.post(
                    "/api/studio/proj_fv_test/jobs/vid_01",
                    json={"mode": "workspace", "payload": layered_clip},
                )
                self.assertEqual(r_job2.status_code, 200)
                jid2 = r_job2.json()["jobId"]
                r_cancel = client.post(f"/api/studio/jobs/{jid2}/cancel")
                self.assertEqual(r_cancel.status_code, 200)
                self.assertEqual(r_cancel.json()["status"], "cancelled")

                # Original video file remains completely untouched
                self.assertTrue(vid_path.is_file())

    def test_fast_seek_grouping_and_lossless_multi_segment_tiers(self):
        # 1. Contiguous speed-curve sub-pieces stay in 1 bounded input group
        curve_pieces = [
            (900.0, 910.0, 1.2, 1.0, 50.0, 50.0),
            (910.0, 920.0, 0.5, 1.0, 50.0, 50.0),
            (920.0, 930.0, 1.4, 1.0, 50.0, 50.0),
        ]
        g_curve = studio_service._group_pieces_for_fast_seek(curve_pieces)
        self.assertEqual(len(g_curve), 1)
        self.assertAlmostEqual(g_curve[0]["start"], 900.0)
        self.assertAlmostEqual(g_curve[0]["end"], 930.0)
        self.assertEqual(len(g_curve[0]["items"]), 3)

        # 2. Discontiguous splits across a 28-min video produce separate fast-seek inputs
        split_pieces = [
            (0.0, 60.0, 1.0, 1.0, 50.0, 50.0),
            (1200.0, 1260.0, 1.0, 1.0, 50.0, 50.0),
            (1600.0, 1680.0, 1.0, 1.0, 50.0, 50.0),
        ]
        g_split = studio_service._group_pieces_for_fast_seek(split_pieces)
        self.assertEqual(len(g_split), 3)
        self.assertEqual([(g["start"], g["end"]) for g in g_split], [(0.0, 60.0), (1200.0, 1260.0), (1600.0, 1680.0)])

        # 3. Excess fragments merge smallest gaps cleanly down to max_groups
        many = [(i * 10.0, i * 10.0 + 3.0, 1.0, 1.0, 50.0, 50.0) for i in range(20)]
        g_capped = studio_service._group_pieces_for_fast_seek(many, max_groups=8)
        self.assertLessEqual(len(g_capped), 8)
        self.assertEqual(sum(len(g["items"]) for g in g_capped), 20)

        if not ffmpeg_setup.ensure_ffmpeg():
            return

        # 4. Live Tier 1.5 (lossless multi-segment concat) + Tier 2.5 (lossless concat + music mix)
        with tempfile.TemporaryDirectory() as tmp:
            proj_dir = Path(tmp) / "02-Full-Video" / "FastConcatTest"
            proj_dir.mkdir(parents=True)
            assets_dir = proj_dir / studio_service.STUDIO_ASSETS_DIR
            assets_dir.mkdir(parents=True)
            vid_path = proj_dir / "keyframe_dense.mp4"
            bgm_path = assets_dir / "bgm.wav"

            # Dense keyframes (-g 12 = 0.5s GOP) like standard YouTube/camera MP4s
            gen = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "testsrc=duration=10:size=320x180:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=10",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "12", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(vid_path),
                ],
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(gen.returncode, 0, gen.stderr)
            gen_a = subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=660:duration=6", str(bgm_path)],
                capture_output=True, text=True, timeout=20, check=False,
            )
            self.assertEqual(gen_a.returncode, 0, gen_a.stderr)

            fake_proj = {
                "project_id": "proj_fast_concat",
                "workspace_name": "FastConcatTest",
                "action": "type_yt_video",
                "category": "02-Full-Video",
                "folder_path": str(proj_dir),
                "files": [
                    {
                        "id": "vid_fc",
                        "title": "FastConcatTest",
                        "filename": "keyframe_dense.mp4",
                        "file_path": str(vid_path),
                        "type": "video",
                        "action": "type_yt_video",
                    }
                ],
            }
            two_blocks = [
                {"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 3.0, "volume": 100, "speedMode": "normal", "speed": 1.0},
                {"id": "seg_2", "sourceStart": 6.5, "sourceEnd": 9.5, "volume": 100, "speedMode": "normal", "speed": 1.0},
            ]

            with patch.object(studio_service.storage_manager, "get_storage_root", return_value=tmp), \
                    patch.object(studio_service.vault_service, "list_vault_projects", return_value=[fake_proj]):
                # Tier 1.5: Lossless multi-segment concat (no effects, no audio mix)
                stages_t15 = []
                out_t15, _, err_t15 = studio_service.export_studio_clip(
                    "proj_fast_concat",
                    "vid_fc",
                    {"cropRatio": "original", "fade": 0, "segments": two_blocks},
                    stage_cb=stages_t15.append,
                )
                self.assertIsNone(err_t15)
                self.assertTrue(out_t15 and Path(out_t15).is_file())
                self.assertIn("Joining clips...", stages_t15)
                self.assertNotIn("Rendering video...", stages_t15)
                dur_t15, _, _ = studio_service._probe_video_info(out_t15)
                self.assertAlmostEqual(dur_t15, 6.0, delta=1.2)

                # Tier 2.5: Multi-segment lossless video copy + background music mix (0 video re-encode)
                stages_t25 = []
                out_t25, _, err_t25 = studio_service.export_studio_clip(
                    "proj_fast_concat",
                    "vid_fc",
                    {
                        "cropRatio": "original",
                        "fade": 0,
                        "segments": two_blocks,
                        "audioClips": [
                            {
                                "id": "aud_1",
                                "name": "bgm.wav",
                                "assetName": "bgm.wav",
                                "sourceDur": 6.0,
                                "timelineStart": 0.5,
                                "trimStart": 1.0,
                                "trimEnd": 4.0,
                                "volume": 40,
                                "fadeIn": 0.2,
                                "fadeOut": 0.2,
                                "keyframes": [],
                            }
                        ],
                    },
                    stage_cb=stages_t25.append,
                )
                self.assertIsNone(err_t25)
                self.assertTrue(out_t25 and Path(out_t25).is_file())
                self.assertIn("Joining clips...", stages_t25)
                self.assertIn("Mixing audio...", stages_t25)
                self.assertNotIn("Rendering video...", stages_t25)
                dur_t25, _, _ = studio_service._probe_video_info(out_t25)
                self.assertAlmostEqual(dur_t25, 6.0, delta=1.2)

                # 5. Smart Render Cache: repeating identical export reuses cached MP4 instantaneously
                stages_cached = []
                out_cached, _, err_cached = studio_service.export_studio_clip(
                    "proj_fast_concat",
                    "vid_fc",
                    {
                        "cropRatio": "original",
                        "fade": 0,
                        "segments": two_blocks,
                        "audioClips": [
                            {
                                "id": "aud_1",
                                "name": "bgm.wav",
                                "assetName": "bgm.wav",
                                "sourceDur": 6.0,
                                "timelineStart": 0.5,
                                "trimStart": 1.0,
                                "trimEnd": 4.0,
                                "volume": 40,
                                "fadeIn": 0.2,
                                "fadeOut": 0.2,
                                "keyframes": [],
                            }
                        ],
                    },
                    stage_cb=stages_cached.append,
                )
                self.assertIsNone(err_cached)
                self.assertEqual(out_cached, out_t25)
                self.assertEqual(stages_cached, ["Using cached render..."])

                # 6. Parallel Chunk Render (Tier 3A) triggers on >=20s filtered video + caches cleanly
                long_vid = proj_dir / "long_22s.mp4"
                gen_l = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-i", "testsrc=duration=22:size=320x180:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=22",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "24", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", str(long_vid),
                    ],
                    capture_output=True, text=True, timeout=30, check=False,
                )
                self.assertEqual(gen_l.returncode, 0, gen_l.stderr)
                fake_proj["files"].append(
                    {
                        "id": "vid_long",
                        "title": "Long22s",
                        "filename": "long_22s.mp4",
                        "file_path": str(long_vid),
                        "type": "video",
                        "action": "type_yt_video",
                    }
                )
                stages_par = []
                prog_par = []
                out_par, _, err_par = studio_service.export_studio_clip(
                    "proj_fast_concat",
                    "vid_long",
                    {
                        "cropRatio": "original",
                        "fade": 0.5,
                        "color": {"preset": "vivid", "brightness": 4, "contrast": 12, "saturation": 28, "exposure": 6, "warmth": 6, "sharpness": 10},
                        "segments": [{"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 22.0, "volume": 100, "speedMode": "normal", "speed": 1.0}],
                    },
                    progress_cb=prog_par.append,
                    stage_cb=stages_par.append,
                )
                self.assertIsNone(err_par)
                self.assertTrue(out_par and Path(out_par).is_file())
                self.assertTrue(any("parallel" in s.lower() for s in stages_par), stages_par)
                self.assertIn("Finalizing video...", stages_par)
                self.assertTrue(len(prog_par) > 0 and max(prog_par) >= 94)
                dur_par, _, _ = studio_service._probe_video_info(out_par)
                self.assertAlmostEqual(dur_par, 22.0, delta=0.8)

                # 7. Quality badge preserves 1080p for 1920x960 cinema/ultrawide (never mislabeled 960p)
                self.assertEqual(studio_service._infer_quality_label(1920, 960, 1920, 960, "1080"), "1080p")
                self.assertEqual(studio_service._infer_quality_label(1920, 960), "1080p")
                self.assertEqual(studio_service._infer_quality_label(1080, 1920), "1080p")
                self.assertEqual(studio_service._infer_quality_label(3840, 1920), "2160p")
                self.assertEqual(studio_service._infer_quality_label(1280, 640), "720p")

                # 8. Tier 0 Zero-FFmpeg Instant Passthrough when clip has 0 edits (full source untouched)
                stages_t0 = []
                out_t0, name_t0, err_t0 = studio_service.export_studio_clip(
                    "proj_fast_concat",
                    "vid_fc",
                    {
                        "cropRatio": "original",
                        "fade": 0,
                        "segments": [{"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 10.0, "volume": 100, "speedMode": "normal", "speed": 1.0}],
                    },
                    stage_cb=stages_t0.append,
                )
                self.assertIsNone(err_t0)
                self.assertEqual(stages_t0, ["Ready"])
                self.assertEqual(Path(out_t0).resolve(), vid_path.resolve())
                self.assertEqual(name_t0, "keyframe_dense.mp4")
                self.assertEqual(
                    Path(studio_service.get_studio_export_path("proj_fast_concat", name_t0)).resolve(),
                    vid_path.resolve(),
                )

                # 9. Background Pre-Render API starts, populates cache, and subsequent export is instant
                client = TestClient(app_module.app, base_url="http://127.0.0.1:8000")
                pr_payload = {
                    "cropRatio": "original",
                    "fade": 0,
                    "color": {"preset": "warm", "brightness": 2, "contrast": 4, "saturation": 8, "warmth": 4},
                    "segments": [{"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 4.0, "volume": 100, "speedMode": "normal", "speed": 1.0}],
                }
                r_pr = client.post("/api/studio/proj_fast_concat/prerender/vid_fc", json={"payload": pr_payload})
                self.assertEqual(r_pr.status_code, 200, r_pr.text)
                self.assertIn(r_pr.json()["status"], ("started", "running", "cached"))
                # Export attaches cleanly to the in-flight pre-render or reuses its finished cache
                out_after_pr, _, err_after_pr = studio_service.export_studio_clip(
                    "proj_fast_concat", "vid_fc", pr_payload
                )
                self.assertIsNone(err_after_pr)
                self.assertTrue(out_after_pr and Path(out_after_pr).is_file())
                r_pr_cancel = client.post("/api/studio/proj_fast_concat/prerender/vid_fc/cancel")
                self.assertEqual(r_pr_cancel.status_code, 200)

                # 10. Auto Cut Silence: 2s tone -> 2s silence -> 2s tone cleanly cuts silent middle pause
                sil_vid = proj_dir / "with_silence.mp4"
                gen_s = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-i", "testsrc=duration=6:size=320x180:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                        "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=2",
                        "-f", "lavfi", "-i", "sine=frequency=520:duration=2",
                        "-filter_complex", "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[a1];[2:a]aformat=sample_rates=48000:channel_layouts=stereo[a2];[3:a]aformat=sample_rates=48000:channel_layouts=stereo[a3];[a1][a2][a3]concat=n=3:v=0:a=1[aout]",
                        "-map", "0:v:0", "-map", "[aout]",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "12", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", str(sil_vid),
                    ],
                    capture_output=True, text=True, timeout=30, check=False,
                )
                self.assertEqual(gen_s.returncode, 0, gen_s.stderr)
                fake_proj["files"].append(
                    {
                        "id": "vid_sil",
                        "title": "SilenceTest",
                        "filename": "with_silence.mp4",
                        "file_path": str(sil_vid),
                        "type": "video",
                        "action": "type_yt_video",
                    }
                )
                r_sil = client.post(
                    "/api/studio/proj_fast_concat/detect-silence/vid_sil",
                    json={"payload": {"segments": [{"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 6.0, "volume": 100, "speedMode": "normal", "speed": 1.0}]}},
                )
                self.assertEqual(r_sil.status_code, 200, r_sil.text)
                sil_data = r_sil.json()
                self.assertTrue(sil_data["ok"])
                self.assertEqual(len(sil_data["segments"]), 2, sil_data)
                self.assertGreaterEqual(sil_data["savedSec"], 1.2)
                self.assertGreaterEqual(sil_data["removedCount"], 1)

                # 11. Smart Audio Suite (Normalize + Denoise + Auto-Duck) stays lossless video copy (Tier 2)
                stages_ae = []
                out_ae, _, err_ae = studio_service.export_studio_clip(
                    "proj_fast_concat",
                    "vid_fc",
                    {
                        "cropRatio": "original",
                        "fade": 0,
                        "audioEnhance": {"normalize": True, "denoise": True, "autoDuck": True},
                        "segments": [{"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 4.0, "volume": 100, "speedMode": "normal", "speed": 1.0}],
                        "audioClips": [
                            {
                                "id": "aud_duck",
                                "name": "bgm.wav",
                                "assetName": "bgm.wav",
                                "sourceDur": 6.0,
                                "timelineStart": 0.0,
                                "trimStart": 0.0,
                                "trimEnd": 4.0,
                                "volume": 45,
                                "fadeIn": 0.0,
                                "fadeOut": 0.0,
                                "keyframes": [],
                            }
                        ],
                    },
                    stage_cb=stages_ae.append,
                )
                self.assertIsNone(err_ae)
                self.assertTrue(out_ae and Path(out_ae).is_file())
                self.assertIn("Mixing audio...", stages_ae)
                self.assertNotIn("Rendering video...", stages_ae)

                # 12. Backend Filmstrip Sprite Cache + Server-Side Waveform Peaks
                r_fs = client.get("/api/studio/proj_fast_concat/filmstrip/vid_fc")
                self.assertEqual(r_fs.status_code, 200, r_fs.text)
                fs_data = r_fs.json()
                self.assertTrue(fs_data["ok"])
                self.assertEqual(len(fs_data["times"]), 24)
                r_img = client.get(fs_data["url"])
                self.assertEqual(r_img.status_code, 200)
                self.assertEqual(r_img.headers["content-type"], "image/jpeg")
                self.assertGreater(len(r_img.content), 1000)

                peaks = studio_service._compute_audio_peaks_ffmpeg(str(bgm_path), 160)
                self.assertEqual(len(peaks), 160)
                self.assertTrue(all(0.05 <= p <= 1.0 for p in peaks))

    def test_wave1_critical_regressions(self):
        if not ffmpeg_setup.ensure_ffmpeg():
            self.skipTest("FFmpeg is required for Wave 1 regression tests")

        with tempfile.TemporaryDirectory() as tmp:
            proj_dir = Path(tmp) / "02-Full-Video" / "Wave1Test"
            proj_dir.mkdir(parents=True)
            # C9: Non-Latin-1 UTF-8 filename (em-dash + emoji)
            utf8_name = "Episode — Cut 🎬.mp4"
            vid_path = proj_dir / utf8_name
            gen = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "testsrc=duration=6:size=320x180:rate=24",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                    "-c:v", "libx264", "-preset", "ultrafast", "-g", "12", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(vid_path),
                ],
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(gen.returncode, 0, gen.stderr)

            fake_proj = {
                "project_id": "proj_wave1",
                "workspace_name": "Wave1Test",
                "action": "type_yt_video",
                "category": "02-Full-Video",
                "folder_path": str(proj_dir),
                "files": [
                    {
                        "id": "vid_u8",
                        "title": "Episode — Cut 🎬",
                        "filename": utf8_name,
                        "file_path": str(vid_path),
                        "type": "video",
                        "action": "type_yt_video",
                    }
                ],
            }

            with patch.object(studio_service.storage_manager, "get_storage_root", return_value=tmp), \
                    patch.object(studio_service.vault_service, "list_vault_projects", return_value=[fake_proj]):
                client = TestClient(app_module.app, base_url="http://127.0.0.1:8000")

                # C5: origMuted persists through /save and reloads cleanly
                r_save = client.post(
                    "/api/studio/proj_wave1/save",
                    json={"clips": [{"id": "vid_u8", "dur": 6.0, "start": 0.0, "end": 6.0, "origMuted": True}]},
                )
                self.assertEqual(r_save.status_code, 200)
                reloaded = client.get("/api/studio/proj_wave1").json()["clips"][0]
                self.assertTrue(reloaded.get("origMuted"))

                # C9: Downloading non-Latin-1 UTF-8 exported file returns HTTP 200 with RFC 5987 filename*
                r_prep = client.post(
                    "/api/studio/proj_wave1/export/vid_u8?prepare=1",
                    json={
                        "cropRatio": "original",
                        "fade": 0,
                        "segments": [{"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 3.0, "volume": 100, "speedMode": "normal", "speed": 1.0}],
                    },
                )
                self.assertEqual(r_prep.status_code, 200, r_prep.text)
                r_dl = client.get(r_prep.json()["downloadUrl"])
                self.assertEqual(r_dl.status_code, 200, r_dl.text)
                cd = r_dl.headers.get("content-disposition", "")
                self.assertIn("attachment", cd.lower())
                self.assertIn("filename*", cd.lower())
                self.assertGreater(len(r_dl.content), 1000)

                # C10: Multi-segment lossless concat where seg_1 has volume=0 and seg_2 has volume=100
                # MUST NOT drop audio stream or corrupt concat demuxer
                out_mixvol, _, err_mixvol = studio_service.export_studio_clip(
                    "proj_wave1",
                    "vid_u8",
                    {
                        "cropRatio": "original",
                        "fade": 0,
                        "segments": [
                            {"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 2.5, "volume": 0, "speedMode": "normal", "speed": 1.0},
                            {"id": "seg_2", "sourceStart": 3.5, "sourceEnd": 6.0, "volume": 100, "speedMode": "normal", "speed": 1.0},
                        ],
                    },
                )
                self.assertIsNone(err_mixvol)
                self.assertTrue(out_mixvol and Path(out_mixvol).is_file())
                self.assertTrue(studio_service._probe_has_audio(out_mixvol), "Audio stream was dropped when seg_1 had volume=0!")
                dur_mv, _, _ = studio_service._probe_video_info(out_mixvol)
                self.assertAlmostEqual(dur_mv, 5.0, delta=0.8)

                # C8: Atomic export commit leaves zero stray .tmp.mp4 or .cache.json.*.tmp files
                exp_dir = proj_dir / studio_service.STUDIO_EXPORTS_DIR
                stray_tmps = [p.name for p in exp_dir.iterdir() if ".tmp" in p.name]
                self.assertEqual(stray_tmps, [], f"Stray temp files left behind: {stray_tmps}")

    def test_wave2_high_regressions(self):
        if not ffmpeg_setup.ensure_ffmpeg():
            self.skipTest("FFmpeg is required for Wave 2 regression tests")

        # H17: Regex matches negative and scientific-notation timestamps from silencedetect
        m_neg = studio_service._SILENCE_START_RE.search("[silencedetect @ 0x1] silence_start: -0.00231")
        m_sci = studio_service._SILENCE_END_RE.search("[silencedetect @ 0x1] silence_end: 2.08333e-05 | silence_duration: 1.2")
        self.assertIsNotNone(m_neg)
        self.assertIsNotNone(m_sci)
        self.assertLess(float(m_neg.group(1)), 0.0)
        self.assertAlmostEqual(float(m_sci.group(1)), 2.08333e-05, places=8)

        # H15: Concurrent _atomic_write_json calls never collide on a shared .tmp path
        with tempfile.TemporaryDirectory() as tmp:
            meta_file = Path(tmp) / "concurrent_meta.json"
            errors = []

            def _writer(idx: int):
                try:
                    for j in range(12):
                        studio_service.vault_service._atomic_write_json(str(meta_file), {"w": idx, "j": j})
                except Exception as exc:
                    errors.append(exc)

            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(_writer, range(4)))
            self.assertEqual(errors, [], f"Concurrent atomic JSON write errors: {errors}")
            self.assertTrue(meta_file.is_file())

            proj_dir = Path(tmp) / "02-Full-Video" / "Wave2Test"
            proj_dir.mkdir(parents=True)

            # H11a: Odd-dimension video (321x181 yuv444p) re-encodes cleanly with even scale filter
            odd_vid = proj_dir / "odd_321x181.mp4"
            gen_odd = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "testsrc=duration=2:size=321x181:rate=24",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv444p",
                    str(odd_vid),
                ],
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(gen_odd.returncode, 0, gen_odd.stderr)

            # H11b: Rotated phone video (320x180 with 90-deg display rotation -> reported as 180x320)
            rot_vid = proj_dir / "rotated_phone.mp4"
            gen_rot = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-display_rotation", "90",
                    "-f", "lavfi", "-i", "testsrc=duration=2:size=320x180:rate=24",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    str(rot_vid),
                ],
                capture_output=True, text=True, timeout=30, check=False,
            )
            if gen_rot.returncode != 0:
                gen_rot = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-i", "testsrc=duration=2:size=320x180:rate=24",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                        "-metadata:s:v:0", "rotate=90",
                        str(rot_vid),
                    ],
                    capture_output=True, text=True, timeout=30, check=False,
                )
            self.assertEqual(gen_rot.returncode, 0, gen_rot.stderr)
            _, rw, rh = studio_service._probe_video_info(str(rot_vid))
            self.assertEqual((rw, rh), (180, 320), f"Rotated video dims were not swapped: {(rw, rh)}")

            # H13: Silent multi-segment video (no audio track) + Smart Audio normalize succeeds
            silent_vid = proj_dir / "no_audio_4s.mp4"
            gen_sil = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "lavfi", "-i", "testsrc=duration=4:size=320x180:rate=24",
                    "-an", "-c:v", "libx264", "-preset", "ultrafast", "-g", "12", "-pix_fmt", "yuv420p",
                    str(silent_vid),
                ],
                capture_output=True, text=True, timeout=30, check=False,
            )
            self.assertEqual(gen_sil.returncode, 0, gen_sil.stderr)

            fake_proj = {
                "project_id": "proj_wave2",
                "workspace_name": "Wave2Test",
                "action": "type_yt_video",
                "category": "02-Full-Video",
                "folder_path": str(proj_dir),
                "files": [
                    {"id": "vid_odd", "title": "Odd", "filename": odd_vid.name, "file_path": str(odd_vid), "type": "video", "action": "type_yt_video"},
                    {"id": "vid_noaud", "title": "NoAud", "filename": silent_vid.name, "file_path": str(silent_vid), "type": "video", "action": "type_yt_video"},
                ],
            }

            with patch.object(studio_service.storage_manager, "get_storage_root", return_value=tmp), \
                    patch.object(studio_service.vault_service, "list_vault_projects", return_value=[fake_proj]):
                # H11a live render check
                out_odd, _, err_odd = studio_service.export_studio_clip(
                    "proj_wave2",
                    "vid_odd",
                    {
                        "cropRatio": "original",
                        "fade": 0,
                        "color": {"preset": "vivid", "brightness": 4, "contrast": 8, "saturation": 14},
                        "segments": [{"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 2.0, "volume": 100, "speedMode": "normal", "speed": 1.0}],
                    },
                )
                self.assertIsNone(err_odd)
                self.assertTrue(out_odd and Path(out_odd).is_file())
                _, ow, oh = studio_service._probe_video_info(out_odd)
                self.assertEqual((ow % 2, oh % 2), (0, 0), f"Output dims not even: {(ow, oh)}")

                # H13 live render check: silent multi-segment + normalize ON
                out_na, _, err_na = studio_service.export_studio_clip(
                    "proj_wave2",
                    "vid_noaud",
                    {
                        "cropRatio": "original",
                        "fade": 0,
                        "audioEnhance": {"normalize": True, "denoise": True, "autoDuck": False},
                        "segments": [
                            {"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 1.5, "volume": 100, "speedMode": "normal", "speed": 1.0},
                            {"id": "seg_2", "sourceStart": 2.0, "sourceEnd": 3.5, "volume": 100, "speedMode": "normal", "speed": 1.0},
                        ],
                    },
                )
                self.assertIsNone(err_na)
                self.assertTrue(out_na and Path(out_na).is_file())

                # H14: Corrupt non-audio bytes uploaded as fake.mp3 -> HTTP 400 and zero leftover asset
                client = TestClient(app_module.app, base_url="http://127.0.0.1:8000")
                r_bad = client.post(
                    "/api/studio/proj_wave2/music?clip_id=vid_odd&filename=fake.mp3",
                    content=b"not an audio file at all just plain text bytes",
                    headers={"Content-Type": "application/octet-stream"},
                )
                self.assertEqual(r_bad.status_code, 400, r_bad.text)
                assets_dir = proj_dir / studio_service.STUDIO_ASSETS_DIR
                if assets_dir.exists():
                    self.assertEqual(list(assets_dir.iterdir()), [], "Corrupt audio upload left stray file behind")

                # H14: Streaming byte cap returns HTTP 413 without reading past cap
                with patch.object(studio_service, "MAX_AUDIO_BYTES", 512):
                    r_big = client.post(
                        "/api/studio/proj_wave2/music?clip_id=vid_odd&filename=huge.mp3",
                        content=b"0" * 4096,
                        headers={"Content-Type": "application/octet-stream"},
                    )
                    self.assertEqual(r_big.status_code, 413, r_big.text)

                # H12: Watchdog timer terminates a stalled process cleanly on timeout
                import sys as _sys
                res_to = studio_service._run_ffmpeg_with_progress(
                    [_sys.executable, "-c", "import time; time.sleep(10)", "dummy_out"],
                    total_dur_sec=5.0,
                    cancel_ctx={"event": __import__("threading").Event(), "proc": None, "procs": set(), "lock": __import__("threading").Lock()},
                    timeout=1,
                )
                self.assertEqual(res_to.returncode, -1)
                self.assertIn("timed out", res_to.stderr.lower())

    def test_wave3_medium_low_regressions(self):
        # M10: Short segment (0.35s) with speed curve does not explode into 10 sub-pieces
        short_curve = [
            {
                "id": "seg_short",
                "sourceStart": 1.0,
                "sourceEnd": 1.35,
                "volume": 100,
                "speedMode": "curve",
                "speed": 1.0,
                "curvePreset": "dip",
                "curvePoints": [1.4, 0.9, 0.4, 0.9, 1.4],
                "curvePositions": [0.0, 0.25, 0.5, 0.75, 1.0],
                "cropX": 50.0,
                "cropY": 50.0,
            }
        ]
        pieces_short = studio_service._expand_segments_to_pieces(short_curve)
        self.assertLessEqual(len(pieces_short), 2, f"Short curve expanded into too many pieces: {pieces_short}")

        with tempfile.TemporaryDirectory() as tmp:
            proj_dir = Path(tmp) / "02-Full-Video" / "Wave3 #Special %Test"
            proj_dir.mkdir(parents=True)
            vid_path = proj_dir / "clip #1 50%?.mp4"
            # Wait: Windows forbids '?' in filenames; use '#' and '%' which are valid on Windows
            vid_path = proj_dir / "clip #1 50%.mp4"
            img_path = proj_dir / "poster.jpg"
            img_path.write_bytes(b"fakejpg")

            if ffmpeg_setup.ensure_ffmpeg():
                gen = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-f", "lavfi", "-i", "testsrc=duration=3:size=320x180:rate=24",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", str(vid_path),
                    ],
                    capture_output=True, text=True, timeout=30, check=False,
                )
                self.assertEqual(gen.returncode, 0, gen.stderr)
            else:
                vid_path.write_bytes(b"0" * 2048)

            fake_proj = {
                "project_id": "proj_wave3",
                "workspace_name": "Wave3 Special",
                "action": "type_yt_video",
                "category": "02-Full-Video",
                "folder_path": str(proj_dir),
                "files": [
                    {"title": "Poster", "filename": img_path.name, "file_path": str(img_path), "type": "image"},
                    {"title": "Video 1", "filename": vid_path.name, "file_path": str(vid_path), "type": "video"},
                ],
            }
            (proj_dir / "meta.json").write_text(__import__("json").dumps([fake_proj], indent=2), encoding="utf-8")

            with patch.object(studio_service.storage_manager, "get_storage_root", return_value=tmp), \
                    patch.object(studio_service.vault_service, "list_vault_projects", return_value=[fake_proj]):
                # M15: _media_vault_url encodes '#' and '%' cleanly
                url = studio_service._media_vault_url(str(vid_path))
                self.assertIn("%23", url)
                self.assertIn("%25", url)
                self.assertNotIn("#", url)

                # M14: Fallback clip_1 skips non-video file at index 0 and resolves to the video!
                _, _, clip_rec, resolved_src, err = studio_service._resolve_project_clip("proj_wave3", "clip_1")
                self.assertIsNone(err)
                self.assertEqual(Path(resolved_src).resolve(), vid_path.resolve())
                self.assertEqual(clip_rec["type"], "video")

                # M16: Malformed numeric fields in save_studio_state do not crash
                saved = studio_service.save_studio_state(
                    "proj_wave3",
                    {
                        "customScale": "not-a-number",
                        "posX": "bad",
                        "posY": None,
                        "clips": [
                            {
                                "id": "clip_1",
                                "dur": "3.0",
                                "start": "bad",
                                "end": "3.0",
                                "music": {
                                    "name": "x.mp3",
                                    "assetName": "x.mp3",
                                    "volume": "oops",
                                    "peaks": [0.2, "bad", None, 0.8],
                                },
                            }
                        ],
                    },
                )
                self.assertIsNotNone(saved)
                self.assertEqual(saved["customScale"], 100)
                self.assertEqual(saved["clips"][0]["music"]["peaks"], [0.2, 0.8])

                if ffmpeg_setup.ensure_ffmpeg():
                    # M11: extract_studio_audio supports audioEnhance (normalize+denoise) cleanly with zero stray tmp
                    mp3_path, _, mp3_err = studio_service.extract_studio_audio(
                        "proj_wave3",
                        "clip_1",
                        {
                            "start": 0.0,
                            "end": 3.0,
                            "audioEnhance": {"normalize": True, "denoise": True, "autoDuck": False},
                            "segments": [{"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 3.0, "volume": 100, "speedMode": "normal", "speed": 1.0}],
                        },
                    )
                    self.assertIsNone(mp3_err)
                    self.assertTrue(mp3_path and Path(mp3_path).is_file())
                    exp_dir = proj_dir / studio_service.STUDIO_EXPORTS_DIR
                    self.assertEqual([p.name for p in exp_dir.iterdir() if ".tmp." in p.name], [])

                    # M13: Pre-cancelled export_studio_clip_to_workspace writes zero edited file & zero meta record
                    cancel_ev = __import__("threading").Event()
                    cancel_ev.set()
                    res_ws, err_ws = studio_service.export_studio_clip_to_workspace(
                        "proj_wave3",
                        "clip_1",
                        {"cropRatio": "original", "fade": 0, "segments": [{"id": "seg_1", "sourceStart": 0.0, "sourceEnd": 3.0, "volume": 100, "speedMode": "normal", "speed": 1.0}]},
                        cancel_ctx={"event": cancel_ev, "proc": None, "procs": set(), "lock": __import__("threading").Lock()},
                    )
                    self.assertIsNone(res_ws)
                    self.assertEqual(err_ws, "Cancelled")
                    self.assertEqual([p.name for p in proj_dir.iterdir() if "_edited" in p.name], [])


if __name__ == "__main__":
    unittest.main()
