from ..dss_reader import read_scenario_dir
import pandas as pd
from data_config import gatef, elev_list, flow_list, stn_name, stn_list
import numpy as np


def calc_vel(flow, stage_up, bottom_elev, width):
    # velocity is flow/cross-section
    xs = (stage_up - bottom_elev) * width
    vel = flow / xs
    return vel


def filter_data(data, column, values, start_date=None, end_date=None):
    """Filter data based on a column and a list of values."""
    if start_date:
        data = data[data[column].isin(values)].dropna()
        data = data[(data["datetime"] >= start_date) & (data["datetime"] <= end_date)]
    else:
        data = data[data[column].isin(values)].dropna()
    return data


def rename_gates(data, column, rename_map):
    """Rename values in a column in the DataFrame."""
    data[column] = data[column].replace(rename_map)
    return data


def set_datetime_index(data):
    data.set_index("datetime", inplace=True)
    data = data["value"]
    return data


def prepare_full_data(sdg_flow, sdg_stage, sdg_gateop, hydro_wl, gatef):
    """
    Prepare gate data dictionary from input datasets.

    Parameters:
    - sdg_flow: DataFrame with flow data.
    - sdg_stage: DataFrame with stage data.
    - sdg_gatop: DataFrame with gate operation data.
    - hydro_wl: Dataframe with water level data.
    - gatef: DataFrame containing gate configuration.
    Returns:
    - Dictionary containing gate data.
    """
    full_data = {}
    for i, gate_name in enumerate(gatef["name"]):
        flow_data = filter_data(sdg_flow, "gate_op", [gatef["flow_op"][i]])
        gate_data = filter_data(sdg_stage, "gate_op", [gatef["gate_status"][i]])
        gate_data = gate_data[gate_data["unit"] == "FEET"]
        gateop_data = sdg_gateop[sdg_gateop["gate_op"] == gatef["station"][i]]
        hydro_wl_data = hydro_wl[hydro_wl["gate"] == gatef["station"][i]]
        full_data[gatef["ID"][i]] = {
            "name": gatef["name"][i],
            "bottom_elev": gatef["bottom_elev"][i],
            "width": gatef["width"][i],
            "flow_data": flow_data,  # sc2_flow
            "gate_data": gate_data,  # sc2_gate
            "gate_operation_data": gateop_data,  # sc2_gateop
            "water_level_data": hydro_wl_data,  # sc2_wl
        }
    return full_data


def generate_full_model_data(
    data,
    path,
    gatef,
    elev_list,
    flow_list,
    stn_name,
    stn_list,
    start_date=None,
    end_date=None,
):
    sdg = data[path]["sdg"]
    hydro = data[path]["hydro"]
    sdg_stage = filter_data(sdg, "gate_op", elev_list, start_date, end_date)
    sdg_flow = filter_data(sdg, "gate_op", flow_list, start_date, end_date)
    sdg_gateop = filter_data(sdg, "gate_op", stn_list, start_date, end_date)
    gate_names = {"MID_GATEOP": "MHO", "GLC_GATEOP": "DGL", "OLD_GATEOP": "OLD"}
    sdg_gateop = rename_gates(sdg_gateop, "gate_op", gate_names)

    hydro_wl = hydro[hydro["parameter"] == "STAGE"]
    hydro_wl = filter_data(hydro_wl, "gate", stn_name, start_date, end_date)
    full_data = prepare_full_data(sdg_flow, sdg_stage, sdg_gateop, hydro_wl, gatef)

    sdg_flow_GLC_FLOW_FISH = set_datetime_index(full_data["GLC"]["flow_data"])
    sdg_flow_GLC_GATE_UP = set_datetime_index(full_data["GLC"]["gate_data"])
    glc_bottom_elev = full_data["GLC"]["bottom_elev"]
    glc_width = full_data["GLC"]["width"]
    sdg_flow_MID_FLOW_FISH = set_datetime_index(full_data["MID"]["flow_data"])
    sdg_flow_MID_GATE_UP = set_datetime_index(full_data["MID"]["gate_data"])
    mid_bottom_elev = full_data["MID"]["bottom_elev"]
    mid_width = full_data["MID"]["width"]

    sdg_flow_OLD_FLOW_FISH = set_datetime_index(full_data["OLD"]["flow_data"])
    sdg_flow_OLD_GATE_UP = set_datetime_index(full_data["OLD"]["gate_data"])
    old_bottom_elev = full_data["OLD"]["bottom_elev"]
    old_width = full_data["OLD"]["width"]

    full_data["GLC"]["vel"] = pd.DataFrame(
        calc_vel(
            sdg_flow_GLC_FLOW_FISH, sdg_flow_GLC_GATE_UP, glc_bottom_elev, glc_width
        )
    )
    full_data["MID"]["vel"] = pd.DataFrame(
        calc_vel(
            sdg_flow_MID_FLOW_FISH, sdg_flow_MID_GATE_UP, mid_bottom_elev, mid_width
        )
    )
    full_data["OLD"]["vel"] = pd.DataFrame(
        calc_vel(
            sdg_flow_OLD_FLOW_FISH, sdg_flow_OLD_GATE_UP, old_bottom_elev, old_width
        )
    )
    for key in ["GLC", "MID", "OLD"]:
        full_data[key]["vel"]["datetime"] = full_data[key]["vel"].index
        full_data[key]["vel"] = full_data[key]["vel"].reset_index(drop=True)
        full_data[key]["vel"] = full_data[key]["vel"][["datetime", "value"]]

    return full_data


def post_process_gateop(model_data, gate):
    gate_up_df = model_data[gate]["gate_operation_data"][["datetime", "value"]]
    gate_up_df["gate_status"] = gate_up_df["value"] >= 10
    gate_up_df["consecutive_groups"] = (
        gate_up_df["value"] != gate_up_df["value"].shift()
    ).cumsum()
    gate_up_df["min_datetime"] = gate_up_df.groupby("consecutive_groups")[
        "datetime"
    ].transform("min")
    gate_up_df["max_datetime"] = gate_up_df.groupby("consecutive_groups")[
        "datetime"
    ].transform("max")
    consecutive_streaks = (
        gate_up_df.groupby(
            ["consecutive_groups", "value", "min_datetime", "max_datetime"]
        )
        .size()
        .reset_index(name="count")
    )
    consecutive_streaks["streak_duration"] = consecutive_streaks["count"] * 15 / 60
    consecutive_streaks_clean = consecutive_streaks.drop(
        ["value", "consecutive_groups", "max_datetime"], axis=1
    )
    # print(consecutive_streaks_clean.head())
    merged_gate_df = pd.merge(
        gate_up_df,
        consecutive_streaks_clean,
        left_on="min_datetime",
        right_on="min_datetime",
    )
    merged_gate_df = merged_gate_df.drop(["consecutive_groups", "value"], axis=1)
    merged_gate_df = merged_gate_df.rename(
        columns={
            "min_datetime": "gate_min_datetime",
            "max_datetime": "gate_max_datetime",
            "count": "gate_count",
            "streak_duration": "gate_streak_duration",
        }
    )
    return merged_gate_df


def post_process_velocity(model_data, gate):
    vel_zoom_df = model_data[gate]["vel"]
    vel_zoom_df["Velocity_Category"] = np.where(
        vel_zoom_df["value"] >= 8, "Over 8ft/s", "Under 8ft/s"
    )
    # .shift shift value down and compare each value with the previous row; increase value when rows are different
    vel_zoom_df["consecutive_groups"] = (
        vel_zoom_df["Velocity_Category"] != vel_zoom_df["Velocity_Category"].shift()
    ).cumsum()
    vel_zoom_df["min_datetime"] = vel_zoom_df.groupby("consecutive_groups")[
        "datetime"
    ].transform("min")
    vel_zoom_df["max_datetime"] = vel_zoom_df.groupby("consecutive_groups")[
        "datetime"
    ].transform("max")
    vel_zoom_df["date"] = vel_zoom_df["datetime"].dt.date.astype(str)
    consecutive_streaks_vel = (
        vel_zoom_df.groupby(
            ["consecutive_groups", "Velocity_Category", "min_datetime", "max_datetime"]
        )
        .size()
        .reset_index(name="count")
    )
    consecutive_streaks_vel["streak_duration"] = (
        consecutive_streaks_vel["count"] * 15 / 60
    )
    consecutive_streaks_vel_clean = consecutive_streaks_vel.drop(
        ["consecutive_groups", "Velocity_Category", "max_datetime"], axis=1
    )
    merged_vel_df = pd.merge(
        vel_zoom_df,
        consecutive_streaks_vel_clean,
        left_on="min_datetime",
        right_on="min_datetime",
    )
    return merged_vel_df


def post_process_full_data(model_data, gate):
    merged_gate_df = post_process_gateop(model_data, gate)
    merged_vel_df = post_process_velocity(model_data, gate)
    full_merged_df = pd.merge(
        merged_vel_df, merged_gate_df, left_on="datetime", right_on="datetime"
    )
    full_merged_df["time_unit"] = 0.25

    return full_merged_df


# ----------------------------------------------------------------------------------------------------
data = read_scenario_dir("C:/Users/Inigo/Projects/sdg-dashboard/data", v7_filter="_7")
start_zoom = "2016-05-01"
end_zoom = "2016-11-30"
fpv1ma_hydro_full_data = generate_full_model_data(
    data,
    "C:\\Users\\Inigo\\Projects\\sdg-dashboard\\data\\output\\FPV1Ma_hydro_7.dss",
    gatef,
    elev_list,
    flow_list,
    stn_name,
    stn_list,
    start_zoom,
    end_zoom,
)
fpv2ma_hydro_full_data = generate_full_model_data(
    data,
    "C:\\Users\\Inigo\\Projects\\sdg-dashboard\\data\\output\\FPV2Ma_hydro_7.dss",
    gatef,
    elev_list,
    flow_list,
    stn_name,
    stn_list,
    start_zoom,
    end_zoom,
)
full_data = post_process_full_data(fpv2ma_hydro_full_data, "GLC")
print(full_data.head())
