# Standard library imports
import os
import sys
import logging
import argparse

# Third party imports
import jwt
import requests
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


load_dotenv()

app = Flask(__name__)

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")


SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("spotifriends")


def verify_supabase_webhook(request):
    token = request.headers.get("Authorization")
    if not token:
        raise ValueError("No webhook signature provided")
    try:
        jwt.decode(token, SUPABASE_JWT_SECRET, algorithms=["HS256"])
        return True
    except jwt.InvalidTokenError:
        return False



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
                            f"playlists for user1 {user1_playlists is None}, "
                            f"playlists for user2 {user2_playlists is None}")

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
        if not check_playlist_following(access_token2, user1_toptracks):
            print(f"New follower relationship: {user2} follows {user1}")
            follow_playlist(
                access_token2, user1_toptracks, public=False
            )
            add_top_tracks_to_follower(user1, user2)

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


@app.route("/save-credentials", methods=["POST", "OPTIONS"])
def save_credentials():

    if request.method == "OPTIONS":  # CORS preflight
        return _build_cors_preflight_response()

    print("new")
    print(request.args)  # Query parameters
    print(request.form)  # Form data for POST requests
    print(request.data)  # JSON data for POST requests
    # access_token = request.data.get('access_token')
    # print(f"access_token = {access_token}")
    # if not access_token:
    #     return {'error': 'Access token is required'}, 400

    # Example: Save to the database (replace with your logic)
    # UserCredentials.objects.create(access_token=access_token)

    res = {"message": "Credentials saved successfully"}, 200
    return _corsify_actual_response(res)


@app.route("/callback", methods=["GET"])
def callback():
    print(request.args)  # Query parameters
    print(request.form)  # Form data for POST requests
    print(request.data)  # JSON data for POST requests
    print(request.json)  # JSON data for POST requests
    code = request.args.get("refresh_token")
    # # code = request.args.get('refresh_token')
    # if not code:
    #     print('No code, authorization failed')

    # # Exchange the code for an access token
    # token_url = 'https://accounts.spotify.com/api/token'
    # auth = (CLIENT_ID, CLIENT_SECRET)

    # headers = {
    #     'Content-Type': 'application/x-www-form-urlencoded'
    # }

    # data = {
    #     'code': code,
    #     'redirect_uri': REDIRECT_URI,
    #     'grant_type': 'authorization_code'
    # }

    # response = requests.post(token_url, headers=headers, data=data, auth=auth)
    # response_data = response.json()

    # if 'access_token' in response_data:
    #     access_token = response_data['access_token']
    #     refresh_token = response_data['refresh_token']

    #     # Send access token to the frontend (React app)
    #     return jsonify({'access_token': access_token, 'refresh_token': refresh_token})

    # return 'Error during token exchange', 400

    # Get the access token from Spotify using the authorization code
    # spotipy.oauth2.SpotifyOauthError

    # token_info = sp_oauth.get_access_token(code)
    # access_token = token_info['access_token']

    print(f"refresh_token = {code}")
    # return f"we did it: {code}!", 200
    return redirect("http://localhost:3000"), 200


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


# ------------------ CORS Stuff -----------------

# Apply CORS to your app
# CORS(app, resources={r"/*": {"origins": "*"}})
# CORS(app)
# app.config['CORS_HEADERS'] = 'Content-Type'


# @app.before_request
# def handle_preflight():
#     print("handling preflight")
#     print(request.method)
#     if request.method == "OPTIONS":
#         print("adding control options")
#         print(f"res.headers = {res.headers}")
#         print(f"res.data = {res.data}")
#         res.headers.add("Access-Control-Allow-Origin", "*")
#         res.headers.add("Access-Control-Allow-Methods", "POST, OPTIONS")
#         return res

# @app.route('/save-credentials', methods=['OPTIONS'])
# def save_credentials_options():
#     """Handle preflight OPTIONS requests."""
#     print("handling preflight options")
#     response = jsonify({'message': 'Preflight request successful'})
#     response.headers.add("Access-Control-Allow-Origin", "*")
#     response.headers.add("Access-Control-Allow-Methods", "POST, OPTIONS")
#     response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
#     return response


# def _build_cors_preflight_response():
#     print("handling prerequest in cors preflight")
#     response = make_response()
#     response.headers.add("Access-Control-Allow-Origin", "*")
#     response.headers.add('Access-Control-Allow-Headers', "*")
#     response.headers.add('Access-Control-Allow-Methods', "*")
#     return response

# def _corsify_actual_response(response):
#     response.headers.add("Access-Control-Allow-Origin", "*")
#     return response
