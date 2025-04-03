"""
This script is intended to be ran weekly to update user playlists with the
the top tracks and recommendations of those they follow.
"""

import os
import traceback

from utils import get_user_access_token, add_top_tracks_to_follower, get_custom_playlists, get_all_followed_playlists, get_user_profile, clear_playlist, get_top_tracks_and_recs, get_playlist_track_uris, add_tracks_to_playlist

from supabase import create_client, Client

from dotenv import load_dotenv

load_dotenv()  # Loads .env file

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

if __name__ == "__main__":

    # Get all user id's.
    spotify_users = supabase.table("spotify_tokens").select("user_id", "email").execute()

    print("Iterating through all users...")
    for i, user in enumerate(spotify_users.data):
        print(f"Updating user playlists ({i})", user["email"], user["user_id"])
        user_id = user["user_id"]

        # if user_id != "37e96704-ec5a-4324-b0e3-af03672831f6":
        #     continue

        try:

            # Testing code to only run this script on my profile.
            # if user_id != "37e96704-ec5a-4324-b0e3-af03672831f6":
            #     print("skipping for now...")
            #     continue

            # Ensure we have playlists made for this user.
            user_playlists = get_custom_playlists(user_id)
            if user_playlists is None:
                print(f"SKIPPING: We don't have playlists made for: {user_id}")
                continue

            # Get the user's access token.
            access_token = get_user_access_token(user_id)

            # Clear their previous list of recommendations.
            clear_playlist(access_token, user_playlists["group_playlist"])

            # Identify all other profiles this user follows:
            profile_id = get_user_profile(access_token)["id"]
            all_playlists = get_all_followed_playlists(profile_id, access_token)
            all_playlist_ids = [playlist["id"] for playlist in all_playlists]

            # Find the subset of playlists that represent another user whom they follow.
            result = supabase.table('spotify_playlists')\
                .select('user_id, individual_playlist')\
                .in_('individual_playlist', all_playlist_ids)\
                .execute()

            # For each followed user, add their top tracks and recs to the individual users group playlist.
            for followed_user in result.data:
                followed_id = followed_user["user_id"]

                # We don't need to add the recommend the top tracks of the user
                # to themselves.
                if followed_id == user_id:
                    continue

                # Note: user_id "follows" followed_id
                print(f"Adding top tracks of {followed_id} to the user.")
                add_top_tracks_to_follower(followed_id, user_id)
                print("Successfully added songs")

            # Get the current user's top tracks and recs.
            user_top_uris = get_top_tracks_and_recs(user_id, access_token)
            user_playlist_id = user_playlists["individual_playlist"]

            # Order the uri's so the most recent are at the top.
            prev_uris = get_playlist_track_uris(access_token, user_playlist_id)
            prev_uris = [uri for uri in prev_uris if uri not in user_top_uris]
            all_uris = user_top_uris + prev_uris

            # Save the individual user's top tracks to their top tracks playlist.
            if len(all_uris) > 0:
                clear_playlist(access_token, user_playlist_id)
                add_tracks_to_playlist(access_token, user_playlist_id, all_uris)
                print(f"Adding top tracks to user's own playlist {user_id}")
            else:
                print(f"Couldn't find any top tracks to for user {user_id}")

            # Also, add their top tracks to the top of the friend favorites.
            if len(user_top_uris) > 0:
                add_tracks_to_playlist(access_token, user_playlists["group_playlist"], user_top_uris, position=0)

            print(f"Successfully added the top tracks for {user_id} !!!")

        except Exception as e:
            print(f"An error occurred updating playlists for user={user_id}: {str(e)}")
            print(traceback.format_exc())
