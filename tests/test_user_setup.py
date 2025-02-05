# Standard library imports
import json
import time
import unittest
from threading import Thread

# Third party imports
import pytest
import requests
from supabase import Client
from supabase import create_client

# Local imports
from app import app
from utils import USER_PLAYLISTS
from utils import SpotifyAPI
from utils import unfollow_playlist
from utils import get_custom_playlists
from utils import get_user_access_token
from utils import check_playlist_following
from utils import get_playlist_tracks


SUPABASE_URL = "https://uomomwtzebhxvizaxdyv.supabase.co"
SUPABASE_SERVICE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVvbW9td3R6ZWJoeHZpemF4ZHl2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTczMzYwMzkwNSwiZXhwIjoyMDQ5MTc5OTA1fQ.gSmTqtj-SXz4AkBz7r9xoOI-hnz0KnjPcixB2zBxgec"

USER_PLAYLISTS = {"individual": "My Top Tracks", "group": "Friend Favorites"}

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


class TestUserCreationWebhook(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Start the Flask app in a separate thread
        cls.flask_thread = Thread(target=lambda: app.run(port=5001))
        cls.flask_thread.daemon = True
        cls.flask_thread.start()
        time.sleep(1)  # Give the server a second to start

        # Test user details
        cls.test_user_id = "17738208-d777-4705-9ff4-32aec1b43a09"
        cls.access_token = get_user_access_token(cls.test_user_id)
        cls.webhook_url = "http://localhost:5001/webhook/user-created"

        # Unfollow (on Spotify) and delete (on supabase) exiting playlists.
        cls.unfollow_test_playlists()
        cls.delete_test_playlists()

    @classmethod
    def unfollow_test_playlists(cls):
        """
        Helper method to unfollow test playlists if they exist.
        """
        user_playlists = get_custom_playlists(cls.test_user_id)
        if user_playlists is None:
            return

        # Unfollow both playlists.
        unfollow_playlist(cls.access_token, user_playlists["individual_playlist"])
        unfollow_playlist(cls.access_token, user_playlists["group_playlist"])

    @classmethod
    def delete_test_playlists(cls):
        """
        Helper method to delete test playlists from supabase if they exist.
        """
        supabase.table("spotify_playlists").delete().eq(
            "user_id", cls.test_user_id
        ).execute()

    def setUp(self):
        pass

    @pytest.mark.run(order=1)
    def test_user_created_webhook(self):

        # Prepare webhook payload
        payload = {
            "type": "INSERT",
            "table": "spotify_tokens",
            "record": {
                "user_id": self.test_user_id,
                "access_token": self.access_token,
            },
        }

        # Send webhook request
        response = requests.post(
            self.webhook_url, json=payload, headers={"Content-Type": "application/json"}
        )

        # Assert response is successful
        self.assertEqual(response.status_code, 200)

        # Give Spotify API a moment to create the playlists
        time.sleep(2)

        # Verify playlists were created
        playlists = get_custom_playlists(self.test_user_id)
        self.assertIsInstance(playlists, dict)
        playlist_names = list(playlists.keys())

        self.assertIn("individual_playlist", playlist_names)
        self.assertIn("group_playlist", playlist_names)

        # Verify the correct number of songs were added.
        individual_tracks = get_playlist_tracks(
            self.access_token, playlists["individual_playlist"]
        )
        group_tracks = get_playlist_tracks(
            self.access_token, playlists["group_playlist"]
        )
        self.assertEqual(len(individual_tracks), 3)
        self.assertEqual(len(group_tracks), 0)

    @pytest.mark.run(order=2)
    def test_user_updated_webhook(self):
        """
        This tests the same endpoint as the user created, but assumes the user
        has authenticated before and we have playlists saved for them.
        """

        # Presume the user has unfollowed the playlists we made for them.
        self.unfollow_test_playlists()

        # Prepare webhook payload
        payload = {
            "type": "INSERT",
            "table": "spotify_tokens",
            "record": {
                "user_id": self.test_user_id,
                "access_token": self.access_token,
            },
        }

        # Send webhook request
        response = requests.post(
            self.webhook_url, json=payload, headers={"Content-Type": "application/json"}
        )

        # Assert response is successful
        self.assertEqual(response.status_code, 200)

        # Give Spotify API a moment to create the playlists
        time.sleep(2)

        # Verify user follows the playlists.
        playlists = get_custom_playlists(self.test_user_id)
        self.assertIsInstance(playlists, dict)

        group_playlist = playlists["group_playlist"]
        individual_playlist = playlists["individual_playlist"]

        for playlist_id in [group_playlist, individual_playlist]:
            is_following = check_playlist_following(
                self.test_user_id, self.access_token, playlist_id
            )
            self.assertTrue(is_following)

        # Verify the correct number of songs were added.
        individual_tracks = get_playlist_tracks(
            self.access_token, playlists["individual_playlist"]
        )
        group_tracks = get_playlist_tracks(
            self.access_token, playlists["group_playlist"]
        )
        self.assertEqual(len(individual_tracks), 3)
        self.assertEqual(len(group_tracks), 0)

    @classmethod
    def tearDownClass(cls):
        # Clean up test playlists again to leave no trace
        cls.unfollow_test_playlists()
        cls.delete_test_playlists()

        # Stop the Flask server
        cls.flask_thread.join(timeout=5)  # Wait up to 5 seconds for thread to finish


if __name__ == "__main__":
    unittest.main()
