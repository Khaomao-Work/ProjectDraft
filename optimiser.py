import requests
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

def solve_itinerary(
    potential_hotels: list[dict], potential_attractions: list[dict],
    trip_duration_days: int, max_daily_hours: int, is_daily_limit_flexible: bool,
    objective_weights: dict, max_budget: float = 0
    ) -> list[dict]:

    if not potential_hotels and potential_attractions:
        first_place = potential_attractions.pop(0)
        first_place['is_hotel'] = True
        potential_hotels.append(first_place)
        
    cleaned_places = []
    for p in potential_hotels + potential_attractions:
        if "name" in p and p["name"]:
            cleaned_places.append({
                "name": p["name"], "lat": p.get("lat"), "lon": p.get("lon"),
                "duration": p.get("duration", 0) if not p.get("is_hotel", False) else 0,
                "is_hotel": p in potential_hotels, "cost": p.get("cost", 0),
                "score": p.get("score", 1), 
                "open_time": p.get("open_time", 0.0), "close_time": p.get("close_time", 24.0)
            })

    if not cleaned_places: return []

    all_places_name = [p["name"] for p in cleaned_places]
    place_to_index = {p["name"]: i for i, p in enumerate(cleaned_places)}
    hotel_indices = [place_to_index[p["name"]] for p in potential_hotels if p.get("name") in place_to_index]
    attraction_indices = [place_to_index[p["name"]] for p in potential_attractions if p.get("name") in place_to_index]

    visiting_time = [p["duration"] for p in cleaned_places]
    cost_list = [p["cost"] for p in cleaned_places]
    score_list = [p["score"] for p in cleaned_places]
    open_time_list = [p["open_time"] for p in cleaned_places]
    close_time_list = [p["close_time"] for p in cleaned_places]

    distance_matrix, time_matrix = get_travel_matrices(cleaned_places)
    if not distance_matrix or not time_matrix: return []

    data = {
        "all_places_name": all_places_name, "hotel_indices": hotel_indices, "attraction_indices": attraction_indices,
        "visiting_time": visiting_time, "d": distance_matrix, "t": time_matrix,
        "day": trip_duration_days, "T_max": max_daily_hours, "flexible": is_daily_limit_flexible,
        "alpha": objective_weights.get("distance_weight"), "beta": objective_weights.get("time_balance_weight"),
        "cost": cost_list, "score": score_list, "open_time": open_time_list,
        "close_time": close_time_list, "max_budget": max_budget
    }

    results = run_optimize_ortools(data)
    if not results.get("daily_routes") or len(results["daily_routes"]) == 0: return []

    itineraries, route_plan = [], []
    for k, route in enumerate(results["daily_routes"]):
        daily_route = []
        if route:
            start_place = next((p for p in potential_hotels + potential_attractions if p["name"] == all_places_name[route[0][0]]), None)
            if start_place: daily_route.append(start_place)
            for dest_index in route:
                dest_place = next((p for p in potential_hotels + potential_attractions if p["name"] == all_places_name[dest_index[1]]), None)
                if dest_place: daily_route.append(dest_place)
        route_plan.append(daily_route)

    itineraries.append({
        "title": "Optimized Route", "total_distance": round(results.get("total_distance", 0), 2),
        "total_time": round(sum(results.get("daily_total_time_spent", [])), 2), "daily_routes": route_plan
    })
    return itineraries

from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

def run_optimize_ortools(data):
    # 1. จัดเตรียมข้อมูลเบื้องต้น
    # ดึงข้อมูลจาก data dictionary ที่คุณจัดเตรียมไว้ใน solve_itinerary
    time_matrix = data['t']
    visiting_time = data['visiting_time']
    open_time = data['open_time']
    close_time = data['close_time']
    num_days = data['day']
    max_daily_time = data['T_max']
    hotel_index = data['hotel_indices'][0] # สมมติว่ามีโรงแรม 1 แห่งเป็นจุดเริ่มต้น/สิ้นสุด
    
    # แปลงเวลาให้เป็นหน่วยเดียวกัน (เช่น นาที หรือ ชั่วโมง) ใน OR-Tools ควรใช้ Integer
    # สมมติว่าเราคูณ 60 เพื่อแปลงชั่วโมงเป็นนาที ให้เป็นจำนวนเต็ม
    
    # 2. สร้าง Routing Index Manager และ Routing Model
    manager = pywrapcp.RoutingIndexManager(len(time_matrix), num_days, hotel_index)
    routing = pywrapcp.RoutingModel(manager)

    # 3. สร้าง Callback สำหรับคำนวณ "เวลาที่ใช้ทั้งหมด" (เวลาเดินทาง + เวลาเที่ยว)
    def time_callback(from_index, to_index):
        # แปลง Index ของ OR-Tools กลับเป็น Index ของตารางข้อมูลเรา
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        
        # เวลาที่ใช้ = เวลาเดินทางจาก from ไป to + เวลาที่แวะเที่ยวในจุด from
        # (ถ้า from เป็นโรงแรม เวลาเที่ยว = 0)
        travel_time = time_matrix[from_node][to_node]
        visit_time = visiting_time[from_node]
        return int((travel_time + visit_time) * 60) # ตัวอย่างแปลงเป็นนาที

    transit_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # 4. เพิ่ม Time Dimension (จัดการเวลาเปิด-ปิด และเวลาเที่ยวสูงสุดต่อวัน)
    time = "Time"
    routing.AddDimension(
        transit_callback_index,
        30,  # Allowable waiting time (ยอมให้รอได้สูงสุดกี่นาทีก่อนสถานที่เปิด)
        int(max_daily_time * 60), # Maximum time per vehicle (เวลาเที่ยวสูงสุดใน 1 วัน)
        False,  # Don't force start cumul to zero (ให้เริ่มออกเดินทางตอนไหนก็ได้)
        time,
    )
    time_dimension = routing.GetDimensionOrDie(time)

    # 5. ใส่ Time Windows (เวลาเปิด-ปิดของแต่ละสถานที่)
    for node in range(len(time_matrix)):
        if node == hotel_index:
            continue # ข้ามโรงแรมไปก่อน หรือจะเซ็ตเวลาออกจากโรงแรมก็ได้
        
        index = manager.NodeToIndex(node)
        # แปลงเวลาเปิดปิดเป็นนาที
        node_open = int(open_time[node] * 60)
        node_close = int(close_time[node] * 60)
        time_dimension.CumulVar(index).SetRange(node_open, node_close)

    # 6. การตั้งค่าให้ "บางสถานที่ไม่ไปก็ได้" (Disjunctions)
    # แทนที่จะบังคับให้ไปทุกที่ เรายอมให้ข้ามได้ถ้าเวลาไม่พอ โดยแลกกับค่าปรับ (Penalty)
    # ยิ่งสถานที่ไหนคะแนน (Score) สูง ค่าปรับก็ควรจะสูงตาม เพื่อให้ระบบพยายามจัดลงตาราง
    penalty = 10000 
    for node in range(len(time_matrix)):
        if node != hotel_index:
            index = manager.NodeToIndex(node)
            routing.AddDisjunction([index], penalty)

    # 7. กำหนดกลยุทธ์การค้นหาคำตอบ (Search Parameters)
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC)
    # กำหนดเวลาให้ AI คิด (เช่น 5 วินาที)
    search_parameters.time_limit.seconds = 5 

    # 8. สั่งให้ระบบเริ่มประมวลผล
    solution = routing.SolveWithParameters(search_parameters)

    # 9. ดึงผลลัพธ์ออกมาจัดรูปแบบ
    results = {"daily_routes": [], "total_distance": 0}
    if solution:
        for vehicle_id in range(num_days):
            index = routing.Start(vehicle_id)
            route_for_vehicle = []
            while not routing.IsEnd(index):
                node_index = manager.IndexToNode(index)
                route_for_vehicle.append(node_index)
                index = solution.Value(routing.NextVar(index))
            # ใส่จุดสิ้นสุด (กลับโรงแรม)
            route_for_vehicle.append(manager.IndexToNode(index))
            
            # เก็บเฉพาะเส้นทางที่มีการเดินทางจริง (ไม่ใช่อยู่แต่โรงแรม)
            if len(route_for_vehicle) > 2:
                # นำไปแปลงเป็น Format (ต้นทาง, ปลายทาง) แบบที่โค้ดเก่าคุณทำไว้
                formatted_route = [(route_for_vehicle[i], route_for_vehicle[i+1]) for i in range(len(route_for_vehicle)-1)]
                results["daily_routes"].append(formatted_route)

    return results

    def safe_normalize(expr, min_val, max_val):
        diff = max_val - min_val
        return 0 if diff <= 1e-6 else (expr - min_val) / diff

    normalization_dist = safe_normalize(objective_dist, min_d, max_d)
    normalization_time_balance = safe_normalize(objective_time_balance, 0.0, T_max * len(K))
    normalization_slack = safe_normalize(objective_slack, 0.0, T_max * len(K))
    normalization_penalty = safe_normalize(objective_penalty, 0.0, len(A) * 5.0)

    model.objective = minimize((alpha * normalization_dist) + (beta * normalization_time_balance) + (normalization_slack if flexible else normalization_penalty))

    if max_budget > 0: model += xsum(cost[i] * y[i][k] for i in A for k in K) <= max_budget
    if target_category != "None":
        target_indices = [i for i in A if category[i] == target_category]
        if target_indices: model += xsum(y[i][k] for i in target_indices for k in K) >= 1

    for k in K:
        for q in H: model += w[q][k] >= 8.0 
        for i in N:
            # ⚠️ แก้ Time Paradox บังคับทิศทางเวลาพุ่งไปข้างหน้าเฉพาะตอนไปที่เที่ยว
            for j in A: 
                if i != j: model += w[j][k] >= w[i][k] + visiting_time[i] + t[i][j] - M * (1 - x[i][j][k])
            if i in A:
                model += w[i][k] >= open_time[i] - M * (1 - y[i][k])
                model += w[i][k] <= close_time[i] + M * (1 - y[i][k])

    for j in A:
        model += xsum(x[i][j][k] for i in N if i != j for k in K) == (1 if flexible else xsum(y[j][k] for k in K))
    for i in A:
        model += xsum(x[i][j][k] for j in N if j != i for k in K) == (1 if flexible else xsum(y[i][k] for k in K))

    for k in K:
        model += xsum(x[q][j][k] for q in H for j in A if j != q) <= 1 
        model += xsum(x[i][q][k] for q in H for i in A if i != q) <= 1
        for i in A:
            model += xsum(x[i][j][k] for j in N if j != i) == y[i][k]
            model += xsum(x[j][i][k] for j in N if j != i) == y[i][k]
            for j in A:
                if i != j: model.add_constr(u[i][k] - u[j][k] + n * x[i][j][k] <= n - 1)
        for q in H: model += u[q][k] == 0
        for i in A:
            model.add_constr(u[i][k] >= y[i][k])
            model.add_constr(u[i][k] <= (n-1)*(y[i][k]))

        travel_term = xsum(t[i][j]*x[i][j][k] for i in N for j in N if i != j)
        visit_term = xsum(visiting_time[j]*y[j][k] for j in N)
        model += travel_term + visit_term <= T_max + (slack[k] if flexible else 0)
        model += T[k] == travel_term + visit_term

    model += T_avg == xsum(T[k] for k in K) / len(K)
    for k in K:
        model += Z[k] >= T[k] - T_avg
        model += Z[k] >= T_avg - T[k]

    if len(K) > 1:
        for k in range(1, len(K)):
            for q in H: model += xsum(x[q][j][k] for j in A) == xsum(x[i][q][k-1] for i in A)
    for q in H: model += (xsum(x[q][j][0] for j in A)) - (xsum(x[i][q][0] for i in A)) == 0
    for k in K:
        for q in H:
            for r in H:
                if q != r: model.add_constr(x[q][r][k] == 0)

    results = {"total_distance": 0, "daily_routes": [], "daily_travel_time": [], "daily_visit_time": [], "daily_total_time_spent": [], "daily_distance": []}

    if model.optimize() in [OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE]:
        total_dist = 0
        for k in K:
            total_travel_time = sum(t[i][j]*x[i][j][k].x for i in N for j in N if i!=j and x[i][j][k].x and x[i][j][k].x > 0.5)
            total_visit_time = sum(visiting_time[j]*y[j][k].x for j in N if j not in H and y[j][k].x and y[j][k].x > 0.5)
            day_dist = sum(d[i][j]*x[i][j][k].x for i in N for j in N if i!=j and x[i][j][k].x and x[i][j][k].x > 0.5)
            total_dist += day_dist
            
            route, start_hotel = [], next((q for q in H for j in N if j != q and x[q][j][k].x and x[q][j][k].x > 0.5), None)
            if start_hotel is None:
                results["daily_routes"].append([]); continue

            current = start_hotel
            while True:
                next_node = next((j for j in N if j != current and x[current][j][k].x and x[current][j][k].x > 0.5), None)
                if next_node is None: break
                route.append((current, next_node))
                if next_node == start_hotel: break
                current = next_node

            results["daily_routes"].append(route)
            results["daily_travel_time"].append(total_travel_time)
            results["daily_visit_time"].append(total_visit_time)
            results["daily_total_time_spent"].append(total_travel_time + total_visit_time)
            results["daily_distance"].append(day_dist)

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
                d_mat.append([c.get('distance', float('inf')) / 1000 for c in row])
                t_mat.append([c.get('time', float('inf')) / 3600 for c in row])
            return d_mat, t_mat
    except Exception: pass
    return [], []
