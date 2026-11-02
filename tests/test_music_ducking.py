import os
from unittest.mock import patch, MagicMock
import pytest

from voicefi.audio.music_ducking import duck_background_music, _duck_active_player, _restore_active_player


def test_duck_background_music_mock_env():
    # In test/mock environment, ducking returns None and does not invoke subprocess
    with patch.dict(os.environ, {"VOICEFI_MOCK_AUDIO": "1"}):
        app, vol = _duck_active_player()
        assert app is None
        assert vol is None


def test_duck_background_music_spotify_active():
    with patch.dict(os.environ, {"VOICEFI_MOCK_AUDIO": "0", "VOICEFI_TESTING": "0", "PYTEST_CURRENT_TEST": ""}):
        with patch("sys.platform", "darwin"), patch("subprocess.run") as mock_run:
            # Mock ducking query returning Spotify:80
            mock_duck_res = MagicMock()
            mock_duck_res.returncode = 0
            mock_duck_res.stdout = "Spotify:80\n"

            # Mock restore
            mock_restore_res = MagicMock()
            mock_restore_res.returncode = 0

            mock_run.side_effect = [mock_duck_res, mock_restore_res]

            with duck_background_music(target_volume=25):
                pass

            assert mock_run.call_count == 2
            # First call ducks to 25
            assert "set sound volume to 25" in mock_run.call_args_list[0][0][0][2]
            # Second call restores to 80
            assert 'tell application "Spotify" to set sound volume to 80' in mock_run.call_args_list[1][0][0][2]
