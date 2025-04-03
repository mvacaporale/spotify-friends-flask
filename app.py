# Standard library imports
import os
import sys
import logging
import argparse

# Third party imports
import jwt
import requests
import traceback
from flask import Flask
from flask import jsonify
from flask import request
from flask import redirect
from flask import make_response
from dotenv import load_dotenv
from flask_cors import CORS
from flask_cors import cross_origin


# Local imports
from utils import USER_PLAYLISTS
from utils import supabase
from utils import delete_user_and_data
from utils import follow_playlist
from utils import unfollow_playlist
from utils import get_custom_playlists
from utils import get_user_access_token
from utils import create_and_save_playlist
from utils import clear_playlist
from utils import get_user_top_tracks
from utils import add_tracks_to_playlist
from utils import add_top_tracks_to_follower
from utils import check_playlist_following
from update_group_playlists import run_update_playlists


load_dotenv()

app = Flask(__name__)

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# Configure CORS
CORS(app)

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("spotifriends")

#Disable logging from the Supabase library
logging.getLogger("supabase").setLevel(logging.WARNING)

def verify_supabase_webhook(request):
    token = request.headers.get("Authorization")
    if not token:
        raise ValueError("No webhook signature provided")
    try:
        jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"])
        return True
    except jwt.InvalidTokenError:
        return False
    

def follow_user(follower_user_id, target_user_id):
    """Create a new follower relationship."""
    try:
        response = supabase.table("spotify_follows").upsert({
            "follower_id": follower_user_id,
            "following_id": target_user_id
        }).execute()
        
        if response.data:
            return response.data[0]
        return None
    except Exception as e:
        print(f"Error following user: {e}")
        raise e


@app.route("/create-follow", methods=["POST"])
def handle_new_follower_relationship():

    try:
        # TODO: Checking the request's Authorization?
        # verify_supabase_webhook(request)

        # Access the user ids
        data = request.json
        user1 = data["user1"]
        user2 = data["user2"]

        # Return if the user has clicked their own follow link.
        if user1 == user2:
            return jsonify({"status": "null", "message": "User cannot follow themselves"}), 200

        # Retrieve their access tokens.
        access_token1 = get_user_access_token(user1)
        access_token2 = get_user_access_token(user2)

        # Retrieve their respective top tracks playlists.
        user1_playlists = get_custom_playlists(user1)
        user2_playlists = get_custom_playlists(user2)

        if user1_playlists is None or user2_playlists is None:
            raise Exception("At least one of the users are not in our database: "
                            f"playlists made for user1 ({user1}): {user1_playlists is not None}, "
                            f"playlists made for user2 ({user2}): {user2_playlists is not None}")

        user1_toptracks = user1_playlists["individual_playlist"]
        user2_toptracks = user2_playlists["individual_playlist"]

        # Initiate follower relationship by following the playlists.
        #     public=False => the playlist will not be visible on their profile
        if not check_playlist_following(access_token1, user2_toptracks):
            print(f"New follower relationship: {user1} follows {user1}")
            follow_playlist(
                access_token1, user2_toptracks, public=False
            )
            add_top_tracks_to_follower(user2, user1)

            # Create follower relationship in supabase
            follow_user(user1, user2)

        if not check_playlist_following(access_token2, user1_toptracks):
            print(f"New follower relationship: {user2} follows {user1}")
            follow_playlist(
                access_token2, user1_toptracks, public=False
            )
            add_top_tracks_to_follower(user1, user2)
            
            # Create follower relationship in supabase
            follow_user(user2, user1)


        return (
            jsonify(
                {
                    "status": "success",
                }
            ),
            200,
        )

    except Exception as e:
        print("An error occurred:" + str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/webhook/user-created", methods=["POST"])
def handle_user_created():

    # TODO: Checking the request's Authorization?
    # verify_supabase_webhook(request)

    # Access the user_id
    user_id = request.json["user_id"]

    print(f"User created with ID: {user_id}")

    try:

        user_email = (
            supabase.table("spotify_tokens")
            .select("email")
            .eq("user_id", user_id)
            .execute()
            .data[0]["email"]
        )

        user_playlists = get_custom_playlists(user_id)
        access_token = get_user_access_token(user_id)

        # Case 1: User playlists have been made and we'll double check they're followed.
        if user_playlists is not None:
            print("We already have playlists made for this user.")
            follow_playlist(
                access_token, user_playlists["individual_playlist"], public=True
            )
            follow_playlist(
                access_token, user_playlists["group_playlist"], public=False
            )
            return (
                jsonify(
                    {
                        "status": "success",
                        "message": "Playlists already exist for this user."
                    }
                ),
                200,
            )

        # Case 2: User playlists have not been made yet.
        print("Creating new playlists for this user")
        create_and_save_playlist(
            user_id, user_email, access_token, playlist_type="individual"
        )
        create_and_save_playlist(
            user_id, user_email, access_token, playlist_type="group"
        )
    
        # Ensure playlists are created with zero songs added initially.
        user_playlists = get_custom_playlists(user_id)
        group_playlist = user_playlists["group_playlist"]
        individual_playlist = user_playlists["individual_playlist"]
        clear_playlist(access_token, group_playlist)
        clear_playlist(access_token, individual_playlist)

        # Get user's tops tracks.
        top_tracks = get_user_top_tracks(access_token)

        # Retry for longer time range if no tracks were found.
        if len(top_tracks) == 0:
            top_tracks = get_user_top_tracks(access_token, time_range="long_term")

        # If top tracks we're finally found, add them to the individual playlist.
        if len(top_tracks) != 0:
            top_uris = [track["uri"] for track in top_tracks]
            add_tracks_to_playlist(access_token, individual_playlist, top_uris)

        return (
            jsonify(
                {
                    "status": "success",
                    "individual_playlist_id": individual_playlist, 
                    "group_playlist_id": group_playlist, 
                }
            ),
            200,
        )

    except Exception as e:
        print("An error occurred:" + str(e))
        return jsonify({"status": "error", "message": str(e)}), 500


@app.after_request
def after_request(response):
    """Add CORS headers to every response"""

    # Get the origin from the request
    origin = request.headers.get('Origin', '')
    logger.debug(f"CHECKING CORS headers for origin: {origin}")
    logger.debug(f"Old Response headers: {dict(response.headers)}")
    
    # # Log what we're doing
    
    # # Add CORS headers
    logger.debug(f"Adding CORS headers for origin: {origin}")
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers.add('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
    response.headers.add('Access-Control-Allow-Headers', '*')
    response.headers.add('Access-Control-Max-Age', '3600')  # Cache preflight for 1 hour
    
    logger.debug(f"New Response headers: {dict(response.headers)}")
    logger.debug(f"Response status: {response.status_code}")

    return response

@app.route('/delete-user', methods=['DELETE', 'OPTIONS'])
def delete_user_endpoint():
    """Handle user deletion."""
    logger.info(f"Received {request.method} request to /delete-user")
    logger.debug(f"Request headers: {dict(request.headers)}")
    
    # Handle preflight OPTIONS request
    if request.method == 'OPTIONS':
        logger.info("Handling OPTIONS request")
        return '', 200  # CORS headers are added by after_request

    # Get the user_id from request parameters
    user_id = request.json["user_id"]

    # Validate user_id
    if not user_id:
        return jsonify({"error": "Missing required parameter: user_id"}), 400
    
    # Perform the deletion
    result = delete_user_and_data(user_id)
    logger.info(jsonify(result))

    # Return appropriate response based on the result
    if result["success"]:
        return jsonify(result), 200
    else:
        return jsonify(result), 500


@app.route('/cron/update-playlist', methods=['GET'])
def cron_job():
    """
    An endpoint to run a weekly cron job that updates the user's
    My Top Tracks and Friend Favorites playlists.
    """
    try:
        run_update_playlists()
        return jsonify({"status": "success"}), 200

    except Exception as e:

        logger.info(f"An error occurred updating playlists: {str(e)}")
        logger.info(traceback.format_exc())
        return jsonify({"status": "failed"}), 500


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level",
    )
    args = parser.parse_args()
    logger.setLevel(args.log_level)

    app.run(debug=True)

