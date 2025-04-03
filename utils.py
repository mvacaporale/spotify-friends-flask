from supabase import create_client, Client
from datetime import datetime
import logging
import requests
import base64
from urllib.parse import urlencode
import os
import sys

from dotenv import load_dotenv

load_dotenv()  # Loads .env file

from datetime import datetime, timedelta

import requests
import json


SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

USER_PLAYLISTS = {
    "individual": "My Top Tracks",
    "group": "Friend Favorites"
}

supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)


# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("spotifriends")

#Disable logging from the Supabase library
logging.getLogger("supabase").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

def refresh_access_token(client_id, client_secret, refresh_token):

    url = "https://accounts.spotify.com/api/token"

    credentials = f"{client_id}:{client_secret}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }

    response = requests.post(url, headers=headers, data=data)

    if response.status_code == 200:
        return response.json()
    else:
        response.raise_for_status()


def get_playlist_tracks(access_token, playlist_id):
    """
    Get all tracks from a Spotify playlist
    
    Args:
        access_token (str): Spotify access token to check
        playlist_id: The Spotify ID of the playlist
        
    Returns:
        List of track objects from the playlist
    """
    if not playlist_id:
        raise ValueError("Playlist ID is required")

    tracks = []
    offset = 0
    limit = 100  # Maximum allowed by Spotify API

    while True:
        url = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        params = {
            "limit": limit,
            "offset": offset
        }

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        response = requests.get(url, headers=headers, params=urlencode(params))
        
        if response.status_code != 200:
            raise Exception(f"Failed to get playlist tracks: {response.status_code} - {response.text}")

        json_result = response.json()
        
        # Extract tracks from the response
        items = json_result.get('items', [])
        if not items:
            break

        tracks.extend(items)
        
        # Check if we've received all tracks
        if len(items) < limit:
            break
            
        offset += limit

    return tracks


def is_token_expired(access_token):
    """
    Check if a Spotify access token is expired.
    
    Args:
        access_token (str): Spotify access token to check
        
    Returns:
        bool: True if token is expired or invalid, False if token is valid
    """
    endpoint = "https://api.spotify.com/v1/me"
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    try:
        response = requests.get(endpoint, headers=headers)
        
        # If we get a 401 status code, the token is expired or invalid
        if response.status_code == 401:
            return True
            
        # If we get a 200, the token is valid
        if response.status_code == 200:
            return False
            
        # For any other status code, raise an exception
        response.raise_for_status()
        
    except requests.exceptions.RequestException:
        # If we can't make the request, assume the token is invalid
        return True


def get_user_access_token(user_id):
    tokens = supabase.table("spotify_tokens").select("user_id, access_token, refresh_token").eq("user_id", user_id).execute()
    access_token = tokens.data[0]["access_token"]

    if is_token_expired(access_token):
        new_tokens = refresh_access_token(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET, tokens.data[0]["refresh_token"])
        supabase.table("spotify_tokens").update(
            {
                "access_token": new_tokens["access_token"]
            }
        ).eq("user_id", user_id).execute()
        return new_tokens["access_token"]
    else:
        return access_token


def create_spotify_playlist(
        user_id, access_token, playlist_name, description="",
        public=False, collaborative=True
    ):
    """
    Create a new Spotify playlist for a given user.
    
    Parameters:
    user_id (str): The Spotify user ID
    access_token (str): OAuth access token
    playlist_name (str): Name for the new playlist
    description (str): Playlist description (optional)
    public (bool): Whether the playlist should be public (default: False)
    collaborative (bool): Whether the playlist should be collaborative (default: True)

    Returns:
    dict: Playlist information if successful, None if failed
    """
    
    # Endpoint for creating a playlist
    endpoint = f"https://api.spotify.com/v1/users/{user_id}/playlists"
    
    # Headers for authorization
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    # Playlist data
    playlist_data = {
        "name": playlist_name,
        "description": description,
        "public": public,
        "collaborative": collaborative,
    }
    
    try:
        # Make the POST request to create the playlist
        response = requests.post(
            endpoint,
            headers=headers,
            data=json.dumps(playlist_data)
        )
        
        # Check if the request was successful
        response.raise_for_status()
        
        # Return the playlist information
        return response.json()
        
    except requests.exceptions.RequestException as e:
        print(f"Error creating playlist: {e}")
        return None


def clear_playlist(access_token, playlist_id):
    """
    Remove all tracks from a Spotify playlist.
    
    Args:
        access_token (str): Valid Spotify access token
        playlist_id (str): Spotify playlist ID
    
    Returns:
        bool: True if successful
    """
    endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    try:
        # First get all tracks to collect their URIs
        response = requests.get(endpoint, headers=headers)
        response.raise_for_status()
        
        tracks = response.json()['items']
        
        if not tracks:
            return True  # Playlist is already empty
            
        # Create list of track URIs to remove
        tracks_to_remove = [{"uri": item['track']['uri']} for item in tracks]
        
        # Delete all tracks
        data = {
            "tracks": tracks_to_remove
        }
        
        response = requests.delete(endpoint, headers=headers, json=data)
        response.raise_for_status()
        
        return True
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            raise Exception("Make sure you have permission to modify this playlist")
        raise Exception(f"Error clearing playlist: {e.response.json()}")


def check_playlist_following(access_token, playlist_id):
    """
    Check if a user follows a specific playlist
    
    Args:
        access_token (str): Spotify access token
        playlist_id (str): ID of the playlist to check
    
    Returns:
        bool: True if user follows the playlist, False otherwise
    """
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    
    # Endpoint to check if users follow a playlist
    url = f'https://api.spotify.com/v1/playlists/{playlist_id}/followers/contains'

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        # API returns an array of booleans, one for each user ID provided
        result = response.json()
        return result[0] if result else False
        
    except requests.exceptions.RequestException as e:
        print(f"Error checking playlist following: {e}")
        return False


def get_custom_playlists(user_id):
    """
    Check if an entry exists in a Supabase table.
    
    Args:
        user_id (str): The user ID to check 
    
    Returns:
        Supabase result if user exists, otherwise None.
    """
    
    # Check if user exists
    result = supabase.table("spotify_playlists").select("*")\
        .eq("user_id", user_id)\
        .execute()

    # If no matching entries found, insert new row
    if len(result.data) > 0:
        return result.data[0]
    else:
        return None


def get_user_profile(access_token):
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    response = requests.get('https://api.spotify.com/v1/me', headers=headers)
    return response.json()


def create_and_save_playlist(user_id, user_email, access_token, playlist_type="individual"):
    """
    This creates a new set of playlists that will save the users top tracks
    and the top tracks of the friends they follow.

    It also save the playlist id's into the `spotify_playlist` supabase table.
    """
    assert playlist_type in USER_PLAYLISTS.keys()

    profile_id = get_user_profile(access_token)["id"]
    playlist_name = USER_PLAYLISTS[playlist_type]
    if playlist_type == "individual":
        collab_settings = dict(public=True, collaborative=False)
    else:
        collab_settings = dict(public=False, collaborative=True)

    response = create_spotify_playlist(
        profile_id, access_token,
        playlist_name, description="",
        **collab_settings
    )

    insert_result = supabase.table("spotify_playlists").upsert({
        "user_id": user_id,
        "email": user_email,
        "{}_playlist".format(playlist_type): response["id"],
    }).execute()


def unfollow_playlist(access_token, playlist_id):
    """Unfollow (delete) a playlist"""
    base_url = "https://api.spotify.com/v1"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    response = requests.delete(
        f"{base_url}/playlists/{playlist_id}/followers",
        headers=headers
    )
    response.raise_for_status()
    return response.status_code == 200
    

def follow_playlist(access_token, playlist_id, public=True):
    """Follow a playlist"""
    base_url = "https://api.spotify.com/v1"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    response = requests.put(
        f"{base_url}/playlists/{playlist_id}/followers",
        headers=headers,
        json={
                "public": public,
            }
    )
    response.raise_for_status()
    return response.status_code == 200


def get_user_top_tracks(access_token, time_range="short_term", limit=3):
    """Get user's top tracks
    
    time_range options: short_term (4 weeks), medium_term (6 months), long_term (years)
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    params = {
        "time_range": time_range,
        "limit": limit
    }
    
    response = requests.get(
        "https://api.spotify.com/v1/me/top/tracks",
        headers=headers,
        params=params
    )

    
    if response.status_code == 200:
        return response.json()["items"]
    else:
        raise Exception(f"Failed to get top tracks: {response.text}")


def add_tracks_to_playlist(access_token, playlist_id, track_uris, position=None):
    """
    Add tracks to a collaborative Spotify playlist.

    Args:
        access_token (str): Valid Spotify access token with playlist-modify-public scope
        playlist_id (str): Spotify playlist ID
        track_uris (list): List of Spotify track URIs to add
        position (int): If 0, it will add the songs to the top
    
    Returns:
        dict: Response from the Spotify API
    """
    endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    # Spotify API accepts a maximum of 100 tracks per request
    if len(track_uris) > 100:
        track_uris = track_uris[:100]
    
    data = {
        "uris": track_uris
    }

    if position:
        data["position"] = position

    response = requests.post(endpoint, headers=headers, json=data)
    response.raise_for_status()  # Raise an exception for error status codes
    
    return response.json()


def get_recent_additions_by_user(access_token, playlist_id, days_ago=7, limit=3):
    """
    Get tracks added by a specific user to a playlist within the specified time period.
    
    Args:
        access_token (str): Valid Spotify access token
        playlist_id (str): Spotify playlist ID
        days_ago (int): Number of days to look back (default 7)
        limit (int): Maximum number of tracks to return (default 3)
    
    Returns:
        list: List of dictionaries containing track info and added_at timestamp
    """
    endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    # Calculate the cutoff date
    cutoff_date = datetime.now() - timedelta(days=days_ago)
    
    # Get the playlist tracks with their add dates
    response = requests.get(endpoint, headers=headers)
    response.raise_for_status()
    
    items = response.json()['items']
    spotify_id = get_user_profile(access_token)["id"]
    
    # Filter tracks by user and date
    recent_additions = []
    
    for item in items:
        # Check if the track was added by the specified user
        if item['added_by']['id'] == spotify_id:
            added_at = datetime.strptime(item['added_at'], "%Y-%m-%dT%H:%M:%SZ")
    
            if added_at > cutoff_date:
                recent_additions.append({
                    'track_name': item['track']['name'],
                    'artist': item['track']['artists'][0]['name'],
                    'added_at': item['added_at'],
                    'uri': item['track']['uri']
                })
    
    # Sort by added_at in descending order (most recent first)
    recent_additions.sort(key=lambda x: x['added_at'], reverse=True)
    
    # Take only the first 'limit' tracks
    return recent_additions[:limit]


def get_playlist_track_uris(access_token, playlist_id):
    """
    Add tracks to a collaborative Spotify playlist.

    Args:
        access_token (str): Valid Spotify access token with playlist-modify-public scope
        playlist_id (str): Spotify playlist ID
    
    Returns:
        dict: Response from the Spotify API
    """
    endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }

    response = requests.get(endpoint, headers=headers)
    response.raise_for_status()
    
    # Extract URIs of existing tracks
    return list(item['track']['uri'] for item in response.json()['items'])


def get_top_tracks_and_recs(user_id, access_token):

    # Get user's recent tops tracks.
    user_top_tracks = get_user_top_tracks(access_token)

    # Retry for longer time range if no tracks were found.
    if len(user_top_tracks) == 0:
        user_top_tracks = get_user_top_tracks(access_token, time_range="long_term")

    user_top_uris = [track["uri"] for track in user_top_tracks]
    print("user_top_uris:", user_top_uris)

    # Get recent recommendations from the user.
    user_playlists = get_custom_playlists(user_id)
    assert user_playlists is not None, (
        f"The user has not been added yet: {user_id}")

    user_recs = get_recent_additions_by_user(access_token, user_playlists["individual_playlist"], days_ago=7)
    user_recs_uris = [track["uri"] for track in user_recs]

    # Merge top tracks and recs.
    # Note: We limit recommendation for three per week.
    all_uris = merge_lists_unique_ordered(user_recs_uris[:3], user_top_uris)
    return all_uris


def add_top_tracks_to_follower(user_id, follower_id):
    """
    This function gets the top tracks of `user_id` as well as their recommendations
    and then adds them to the group playlist  of `follower_id`.
    """
    # Get their access token.
    follower_access_token = get_user_access_token(follower_id)
    user_access_token = get_user_access_token(user_id)

    # Get user top tracks and recs.
    users_top_uris = get_top_tracks_and_recs(user_id, user_access_token)

    # Add all recs and top tracks to the followers playlist.
    follower_playlists = get_custom_playlists(follower_id)
    assert follower_playlists is not None, (
        f"The follower has not been added yet: {follower_id}")
    follower_friend_favs = follower_playlists["group_playlist"]

    if len(users_top_uris) > 0:
        print(f"Adding top tracks and songs recs to follower playlist: {follower_friend_favs}")
        add_tracks_to_playlist(user_access_token, follower_friend_favs, users_top_uris)
    else:
        print(f"No top tracks or recommendations found for user: {user_id}")


def merge_lists_unique_ordered(list1, list2):
    """
    Merge two lists while removing duplicates and preserving order.
    First occurrence of each item is kept.
    
    Args:
        list1 (list): First list
        list2 (list): Second list
    
    Returns:
        list: Merged list with duplicates removed, preserving order
    """
    seen = set()
    merged = []
    
    # Process all items from both lists
    for item in list1 + list2:
        # Only add item if we haven't seen it before
        if item not in seen:
            merged.append(item)
            seen.add(item)
    
    return merged


def get_all_followed_playlists(user_id: str, access_token: str):
    """
    Fetch all playlists for a given Spotify user using the Spotify Web API.
    
    Args:
        user_id (str): The Spotify user ID to fetch playlists for
        access_token (str): Valid Spotify OAuth access token
        
    Returns:
        List[Dict]: List of playlist objects containing details like name, ID, tracks count, etc.
    
    Raises:
        requests.exceptions.RequestException: If the API request fails
        ValueError: If the response is invalid or authorization fails
    """

    base_url = f"https://api.spotify.com/v1/users/{user_id}/playlists"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    playlists = []
    limit = 50  # Maximum number of playlists per request
    offset = 0
    
    while True:
        # Make request with pagination parameters
        params = {
            "limit": 50,
            "offset": offset
        }

        response = requests.get(base_url, headers=headers, params=params)
        
        if response.status_code == 401:
            raise ValueError("Invalid or expired access token")
        elif response.status_code != 200:
            raise requests.exceptions.RequestException(
                f"API request failed with status code: {response.status_code}"
            )
            
        data = response.json()
        
        # Add playlists from current page to results
        playlists.extend([{
            'id': playlist['id'],
            'name': playlist['name'],
            'description': playlist['description'],
            'public': playlist['public'],
            'tracks_count': playlist['tracks']['total'],
            'url': playlist['external_urls']['spotify']
        } for playlist in data['items']])
        
        # Check if we've fetched all playlists
        if len(data['items']) < 50:
            break

        offset += limit
    
    return playlists


class SpotifyAPI:
    """Helper class for Spotify API calls"""
    BASE_URL = "https://api.spotify.com/v1"

    def __init__(self, access_token):
        self.headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
    
    def get_current_user_playlists(self):
        """Get all playlists for the current user"""
        response = requests.get(
            f"{self.BASE_URL}/me/playlists",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    
    def create_playlist(self, user_id, name, public=True, description=""):
        """Create a new playlist"""
        response = requests.post(
            f"{self.BASE_URL}/users/{user_id}/playlists",
            headers=self.headers,
            json={
                "name": name,
                "public": public,
                "description": description
            }
        )
        response.raise_for_status()
        return response.json()
    
    def unfollow_playlist(self, playlist_id):
        """Unfollow (delete) a playlist"""
        response = requests.delete(
            f"{self.BASE_URL}/playlists/{playlist_id}/followers",
            headers=self.headers
        )
        response.raise_for_status()
        return response.status_code == 200

    def get_current_user(self):
        """Get current user's profile"""
        response = requests.get(
            f"{self.BASE_URL}/me",
            headers=self.headers
        )
        response.raise_for_status()
        return response.json()
    

def delete_user_and_data(user_id):
    """
    Deletes a user and their associated data from Supabase
    
    Args:
        user_id (str): The UUID of the user to delete
        
    Returns:
        dict: Result of the operation
    """
    try:
        logger.info(f"Starting deletion process for user: {user_id}")

        # Step 1a: Delete associated records from spotify_playlists table
        playlists_result = supabase.table('spotify_playlists').delete().eq('user_id', user_id).execute()
        if hasattr(playlists_result, 'error') and playlists_result.error:
            raise Exception(f"Error deleting spotify_playlists: {playlists_result.error}")
        logger.info(f"Deleted associated playlist records for user: {user_id}")

        # Step 1b: Delete associated records from follow-relationship table.
        follower_result = supabase.table('spotify_follows').delete().eq('follower_id', user_id).execute()
        if hasattr(follower_result, 'error') and follower_result.error:
            raise Exception(f"Error deleting from spotify_follows: {playlists_result.error}")

        following_result = supabase.table('spotify_follows').delete().eq('following_id', user_id).execute()
        if hasattr(following_result, 'error') and following_result.error:
            raise Exception(f"Error deleting from spotify_follows: {playlists_result.error}")
        logger.info(f"Deleted associated follower records for user: {user_id}")

        # Step 2: Delete associated records from spotify_tokens table
        tokens_result = supabase.table('spotify_tokens').delete().eq('user_id', user_id).execute()
        if hasattr(tokens_result, 'error') and tokens_result.error:
            raise Exception(f"Error deleting spotify_tokens: {tokens_result.error}")
        logger.info(f"Deleted associated token records for user: {user_id}")

        # Step 3: Delete the user from Auth
        user_result = supabase.auth.admin.delete_user(user_id)
        if hasattr(user_result, 'error') and user_result.error:
            raise Exception(f"Error deleting user: {user_result.error}")
            
        logger.info(f"Successfully deleted user: {user_id}")
        
        return {
            "success": True,
            "message": f"User {user_id} and all associated data successfully deleted"
        }
        
    except Exception as e:
        logger.error(f"Error during user deletion: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }
