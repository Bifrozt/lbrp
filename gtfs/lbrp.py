import pandas as pd
import geopandas as gpd
from shapely.geometry import Point
from dotenv import load_dotenv
import os
from geopy.distance import geodesic
import sl_rtd as sl
import logging
import pickle
from datetime import datetime, timedelta
import math

# __Author__: pablo-chacon
# __Version__: 1.0.2
# __Date__: 2024-05-23

# Configure logging.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Load .env vars.
load_dotenv()


# Load sites data.
def load_sites_data():
    return sl.load_sites_data()


# Closest three within radius.
def find_nearby_sites(lat, lon, sites_data, radius=1000, n=3):
    user_location = (lat, lon)
    sites_data = sites_data.dropna(subset=['lat', 'lon'])  # Ensure no NaNs in coordinates
    logging.info(f"User location: {user_location}")
    sites_data['distance'] = sites_data.apply(lambda row: geodesic(user_location, (row['lat'], row['lon'])).meters,
                                              axis=1)
    nearby_sites = sites_data[sites_data['distance'] <= radius]
    closest_sites = nearby_sites.nsmallest(n, 'distance')
    return closest_sites


# Fetch real-time departures.
def fetch_departures(site_id, time_window, transport_mode='BUS'):
    try:
        departures = sl.fetch_departures(site_id, time_window, transport_mode)
        if departures:
            logging.info(f"Fetched departures for site ID {site_id}: {departures}")
            return departures
    except Exception as e:
        logging.error(f"Error fetching departures for site ID {site_id}: {e}")
    return []


# Travel time alternative transport modes.
def estimate_travel_time(distance, transport_mode):
    if transport_mode == 'walk':
        speed_kmh = 5  # Average walking speed
    elif transport_mode == 'bike':
        speed_kmh = 15  # Average biking speed
    elif transport_mode == 'car':
        speed_kmh = 50  # Average city driving speed
    else:
        return "N/A"
    travel_time_hours = distance / 1000 / speed_kmh
    travel_time_minutes = travel_time_hours * 60
    return timedelta(minutes=travel_time_minutes)


# Optimize route.
def optimize_route(gdf, sites_data, destination_coords, step=15):
    route = []
    total_points = len(gdf)
    logging.info(f"Total waypoints to process: {total_points}")

    for i in range(0, total_points, step):
        waypoint = gdf.iloc[i]
        if pd.isna(waypoint['Latitude']) or pd.isna(waypoint['Longitude']):
            logging.warning(f"Skipping waypoint with NaN coordinates at index {i}")
            continue
        closest_sites = find_nearby_sites(waypoint['Latitude'], waypoint['Longitude'], sites_data)
        logging.info(
            f"Closest sites for waypoint {i} ({waypoint['Latitude']}, {waypoint['Longitude']}): {closest_sites}")
        if not closest_sites.empty:
            for _, site in closest_sites.iterrows():
                travel_time_to_site = estimate_travel_time(site['distance'], 'walk')
                eta = waypoint['Time'] + travel_time_to_site
                time_window = math.ceil(travel_time_to_site.total_seconds() / 60) + 3
                departures = fetch_departures(site['id'], time_window)
                if departures:  # Only add entries with departures
                    logging.info(f"Found departures for site ID {site['id']} at waypoint {i}")
                    for dep in departures:
                        route.append({
                            "waypoint_lat": waypoint['Latitude'],
                            "waypoint_lon": waypoint['Longitude'],
                            "waypoint_time": waypoint['Time'],
                            "site_id": site['id'],
                            "site_name": site['name'],
                            "site_lat": site['lat'],
                            "site_lon": site['lon'],
                            "destination": dep['destination'],
                            "direction": dep['direction'],
                            "state": dep['state'],
                            "scheduled": dep['scheduled'],
                            "expected": dep['expected'],
                            "line_id": dep['line']['id'],
                            "line_designation": dep['line']['designation'],
                            "transport_mode": dep['line']['transport_mode']
                        })
        else:
            # No nearby sites in range.
            logging.info(f"No nearby sites found for waypoint {i} ({waypoint['Latitude']}, {waypoint['Longitude']})")
            for dest_lat, dest_lon in destination_coords:
                distance = geodesic((waypoint['Latitude'], waypoint['Longitude']), (dest_lat, dest_lon)).meters
                for mode in ['walk', 'bike', 'car']:
                    eta = estimate_travel_time(distance, mode)
                    route.append({
                        "waypoint_lat": waypoint['Latitude'],
                        "waypoint_lon": waypoint['Longitude'],
                        "waypoint_time": waypoint['Time'],
                        "site_id": "N/A",
                        "site_name": "N/A",
                        "site_lat": dest_lat,
                        "site_lon": dest_lon,
                        "destination": f"{mode.capitalize()} to destination",
                        "direction": "N/A",
                        "state": "N/A",
                        "scheduled": "N/A",
                        "expected": (waypoint['Time'] + eta).strftime("%Y-%m-%d %H:%M:%S") if eta != "N/A" else "N/A",
                        "line_id": "N/A",
                        "line_designation": mode.capitalize(),
                        "transport_mode": mode
                    })
    logging.info(f"Route generated with {len(route)} entries.")
    return route


def main():
    logging.info("Loading user trajectory data")
    gdf = pd.read_pickle('gdf.pkl')
    dest = pd.read_pickle('dest.pkl')

    logging.info("Extracting destination coordinates from dest.pkl")
    destination_coords = [(row['Latitude'], row['Longitude']) for _, row in dest.iterrows() if row['is_destination']]

    logging.info(f"Destination coordinates: {destination_coords}")

    logging.info("Loading sites data")
    sites_data = load_sites_data()

    logging.info("Optimizing route")
    optimized_route = optimize_route(gdf, sites_data, destination_coords)

    logging.info("Pickling optimized route")
    with open('optimized_route.pkl', 'wb') as f:
        pickle.dump(optimized_route, f)

    logging.info("Optimized route generation complete")


if __name__ == '__main__':
    main()
