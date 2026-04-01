import requests
import math
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

def run_optimize_ortools(data):
    time_matrix = data['t']
    visiting_time = data['visiting_time']
    open_time = data['open_time']
    close_time = data['close_time']
    num_days = data['day']
    max_daily_time = data['T_max']
    hotel_index = data['hotel_indices'][0] 
    
    manager = pywrapcp.RoutingIndexManager(len(time_matrix), num_days, hotel_index)
    routing = pywrapcp.RoutingModel(manager)

    def time_callback(from_index, to_index):
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        travel_time = time_matrix[from_node][to_node]
        visit_time = visiting_time[from_node]
        return int((travel_time + visit_time) * 60) 

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    time = "Time"
    routing.AddDimension(
        transit_callback_index,
        1440, # ยอมให้รอได้ 24 ชม.
        int(max_daily_time * 60), 
        False, 
        time,
    )
    time_dimension = routing.GetDimensionOrDie(time)

    for node in range(len(time_matrix)):
        if node == hotel_index: continue 
        index = manager.NodeToIndex(node)
        node_open = int(open_time[node] * 60)
        node_close = int(close_time[node] * 60)
        
        # ป้องกันบั๊กเวลา
        if node_open >= node_close: node_close = 1440
        time_dimension.CumulVar(index).SetRange(node_open, node_close)

    # Disjunctions เพื่อให้เลือกข้ามสถานที่ได้ถ้าเวลาไม่พอ
    penalty = 10000 
    for node in range(len(time_matrix)):
        if node != hotel_index:
            index = manager.NodeToIndex(node)
            routing.AddDisjunction([index], penalty)

    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    search_parameters.time_limit.seconds = 5 

    solution = routing.SolveWithParameters(search_parameters)

    results = {"daily_routes": [], "total_distance": 0, "daily_total_time_spent": []}
    
    if solution:
        total_dist = 0
        for vehicle_id in range(num_days):
            index = routing.Start(vehicle_id)
            route_for_vehicle = []
            day_time = 0 
            
            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                route_for_vehicle.append(node_index)
                
                next_index = solution.Value(routing.NextVar(index))
                next_node = manager.IndexToNode(next_index)
                
                # คำนวณระยะทางและเวลาจริง
                dist = data['d'][node_index][next_node]
                total_dist += dist if dist != float('inf') else 0
                day_time += data['t'][node_index][next_node] + data['visiting_time'][node_index]
                
                index = next_index
                
            route_for_vehicle.append(manager.IndexToNode(index))
            
            if len(route_for_vehicle) > 2:
                formatted_route = [(route_for_vehicle[i], route_for_vehicle[i+1]) for i in range(len(route_for_vehicle)-1)]
                results["daily_routes"].append(formatted_route)
                results["daily_total_time_spent"].append(day_time)

        results["total_distance"] = total_dist
    return results

def get_travel_matrices(places: list[dict]) -> tuple[list[list[float]], list[list[float]]]:
    import streamlit as st
    api_key = st.secrets.get("GEOAPIFY_API_KEY")
    if not api_key: return [], []
    coords = [{"location": [p['lon'], p['lat']]} for p in places]
    try:
        resp = requests.post(f"https://api.geoapify.com/v1/routematrix?apiKey={api_key}", json={"mode": "drive", "sources": coords, "targets": coords})
        if resp.status_code == 200:
            d_mat, t_mat = [], []
            for row in resp.json().get('sources_to_targets', []):
                d_mat.append([c.get('distance', 0) / 1000 for c in row])
                t_mat.append([c.get('time', 0) / 3600 for c in row])
            return d_mat, t_mat
    except Exception: pass
    return [], []

def solve_itinerary(
    potential_hotels: list[dict], potential_attractions: list[dict],
    trip_duration_days: int, max_daily_hours: int, is_daily_limit_flexible: bool,
    objective_weights: dict, max_budget: float = 0
    ) -> list[dict]:

    # ทำความสะอาดข้อมูล
    cleaned_places = []
    combined = potential_hotels + potential_attractions
    for p in combined:
        if "name" in p:
            cleaned_places.append({
                "name": p["name"], "lat": p.get("lat"), "lon": p.get("lon"),
                "duration": p.get("duration", 0) if p not in potential_hotels else 0,
                "is_hotel": p in potential_hotels, "cost": p.get("cost", 0),
                "score": p.get("score", 1), 
                "open_time": p.get("open_time", 0.0), "close_time": p.get("close_time", 24.0)
            })

    if not cleaned_places: return []

    all_places_name = [p["name"] for p in cleaned_places]
    hotel_indices = [i for i, p in enumerate(cleaned_places) if p["is_hotel"]]

    distance_matrix, time_matrix = get_travel_matrices(cleaned_places)
    if not distance_matrix: return []

    data = {
        "all_places_name": all_places_name, "hotel_indices": hotel_indices,
        "visiting_time": [p["duration"] for p in cleaned_places],
        "d": distance_matrix, "t": time_matrix,
        "day": trip_duration_days, "T_max": max_daily_hours,
        "open_time": [p["open_time"] for p in cleaned_places],
        "close_time": [p["close_time"] for p in cleaned_places]
    }

    results = run_optimize_ortools(data)
    
    if not results["daily_routes"]: return []

    # แปลงผลลัพธ์กลับเป็นข้อมูลสถานที่
    route_plan = []
    for route in results["daily_routes"]:
        daily_route = []
        # จุดเริ่มต้น
        daily_route.append(next(p for p in combined if p["name"] == all_places_name[route[0][0]]))
        for _, dest_idx in route:
            daily_route.append(next(p for p in combined if p["name"] == all_places_name[dest_idx]))
        route_plan.append(daily_route)

    return [{
        "title": "Optimized Route", 
        "total_distance": round(results["total_distance"], 2),
        "total_time": round(sum(results["daily_total_time_spent"]), 2), 
        "daily_routes": route_plan
    }]
