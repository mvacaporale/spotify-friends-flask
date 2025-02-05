# Standard library imports
import unittest
from unittest.mock import Mock
from unittest.mock import patch

# Local imports
# Assuming your functions are in a module called spotify_service
from utils import get_user_profile
from utils import unfollow_playlist
from utils import get_user_access_token
from utils import create_spotify_playlist


class TestSpotifyService(unittest.TestCase):

    def setUp(self):
        """Set up test fixtures before each test method"""
        self.test_user_id =  "17738208-d777-4705-9ff4-32aec1b43a09"
        self.access_token = get_user_access_token(self.test_user_id)

    def test_create_playlist(self):
        """Test successful playlist creation"""
        # Create user playlist.
        profile_id = get_user_profile(self.access_token)["id"]
        response = create_spotify_playlist(
            profile_id,
            self.access_token,
            playlist_name="Test Playlist",
        )
        print("response", response)


if __name__ == '__main__':
    unittest.main()