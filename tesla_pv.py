#!/usr/bin/env python3 -u

"""
Description

@author: Bernd Kast
@author: Thomas Keller
@copyright: Copyright (c) 2018, Siemens AG
@note:  All rights reserved.
"""
import os
import numpy as np
import teslapy
import json
import requests
import sys
import signal
import time

from datetime import datetime, timedelta
from math import ceil, floor
from typing import List, Dict
from dataclasses import dataclass


def log(message: str):
    print(f"{str(datetime.now())}: {message}")


class TeslaApi:
    def __init__(self, email: str, token: str):
        self.tesla = teslapy.Tesla(email)
        self.token = token

    def _vehicle(self):
        return self.tesla.vehicle_list()[0]
        
    def _battery_data(self):
        powerwall = self.tesla.battery_list()[0]
        return powerwall.get_battery_data()

    def close(self):
        self.tesla.close()

    def call(self, name: str, *args, **kwargs):
        do = f"_{name}"
        if hasattr(self, do) and callable(func := getattr(self, do)):
            if not self.tesla.authorized:
                try:
                    self.tesla.refresh_token(refresh_token = self.token)
                except Exception as e:
                    raise Exception("Refreshing the access token failed; is the refresh_token still valid?") from e
            try:
                return func(*args, **kwargs)
            except:
                self.tesla.refresh_token(refresh_token = self.token)
                return func(*args, **kwargs)
        else:
            raise Exception(f"No method {do} found")


class HistoricData:
    def __init__(self):
        self.timestamp = None
        self.power_history = None
        self.car = dict()
        self.check_period_minutes = 0.5
        self.reset()

    def reset(self):
        self.power_history = list()
        self.timestamp = datetime.now()

    def add(self, power: int) -> List[int]:
        self.power_history.append(power)
        if (datetime.now() - self.timestamp > timedelta(minutes = self.check_period_minutes) and len(self.power_history) > 10):
            history = self.power_history
            self.reset()
            return history
        return list()


@dataclass
class ChargeControlResult:
   vehicle_is_charging: bool
   soc_min_reached: bool
   soc_limit_reached: bool


class ChargeControl:
    def __init__(self, api: TeslaApi, options: Dict[str,str]):
        self.api = api
         # soc below the car is considered empty => full charging speed, regardless of PV / Grid origin
        self.empty_soc = int(options['EMPTY_SOC'])
        self.do_not_interfere_charge_limit_soc = int(options['DO_NOT_INTERFERE_CHARGE_LIMIT'])
        self.do_not_interfere_amperage = int(options['DO_NOT_INTERFERE_AMPERAGE'])
        self.min_amperage = int(options['MIN_AMPERAGE'])
        self.effective_voltage = int(options['EFFECTIVE_VOLTAGE'])
        self.change_of_charge_power = False

    def set_charging(self, vehicle, start):
        log(f"start charging: {start}")
        vehicle.sync_wake_up()
        try:
            if start:
                vehicle.command('START_CHARGE')
            else:
                vehicle.command('STOP_CHARGE')
        except Exception as e:
            log(f"could not {action} charging: {e}".format(action="start" if start else "stop"))

    def set_charge_speed(self, vehicle, amperage):
        vehicle.sync_wake_up()
        # after the wakeup, the current charge state becomes queryable
        cur_amps = vehicle["charge_state"]["charge_current_request"]
        if cur_amps < self.do_not_interfere_amperage and \
                cur_amps != amperage:
            log(f"set amperage {amperage} (was {cur_amps})")
            try:
                vehicle.command("CHARGING_AMPS", charging_amps = amperage)
                self.change_of_charge_power = True
                log(f"amperage set")
            except Exception as e:
                log(f"could not set amperage to {amperage}: {e}")

    # returns a tuple (vehicle_is_charging, soc_min_reached, soc_limit_reached)
    def update_charge_speed(self, power_history: np.array) -> (bool, bool, bool):
        vehicle = self.api.call('vehicle')
        vehicle.sync_wake_up()
        # after the wakeup, the current charge state becomes queryable
        soc = float(vehicle["charge_state"]["battery_level"])
        current_amperage = float(vehicle["charge_state"]["charger_actual_current"])
        current_charge_power = float(vehicle["charge_state"]["charger_power"])
        charge_limit_soc = float(vehicle["charge_state"]["charge_limit_soc"])
        currently_charging = current_charge_power > 0.1
        soc_min_reached = soc >= self.empty_soc
        soc_limit_reached = soc >= charge_limit_soc
        
        # strip first 10 seconds after power change as the charger needs to ramp up (to avoid oszillation)
        if self.change_of_charge_power:
            log(f"strip first seconds because we lately changed the charging speed size: {len(power_history)}")
            self.change_of_charge_power = False
            try:
                power_history = power_history[10:]
            except:
                log(f"power history was too short, could not strip first 10s: {len(power_history)}")

        log(f"current amperage: {current_amperage} A")
        log(f"current charge limit: {int(charge_limit_soc)}%")
        if current_amperage >= self.do_not_interfere_amperage or \
            charge_limit_soc >= self.do_not_interfere_charge_limit_soc:
            log("do not interfere, since charge limit or current amps is above configured values")
            return ChargeControlResult(currently_charging, soc_min_reached, soc_limit_reached)

        if soc < self.empty_soc:
            new_amperage = self.do_not_interfere_amperage - 1
            log(f"charge with {new_amperage} A since SOC is below {self.empty_soc}")
            new_do_charging = True
        else:
            effective_voltage = self.effective_voltage
            if not effective_voltage:
                try:
                    effective_voltage = round(current_charge_power * 1000.0 / current_amperage / 230.0) * 230.0
                except ZeroDivisionError:
                    effective_voltage = 230.0 * 3.0
                effective_voltage = max(230.0, effective_voltage)
            else:
                effective_voltage = 3.0 * 230.0

            consumption_history = power_history - effective_voltage * current_amperage

            # calculate optimal charge power based on current soc
            if abs(np.max(power_history)) < 50:        # hysteresis
                log(f"deviation too small - keeping old chargespeed max: {np.max(power_history)}")
                return ChargeControlResult(currently_charging, soc_min_reached, soc_limit_reached)
            new_charge_power = -np.max(consumption_history)
            new_amperage = floor(new_charge_power / effective_voltage)
            log(f"chargepower: {new_charge_power} W => {new_amperage} A")
            if new_amperage < self.min_amperage:
                new_amperage = self.min_amperage
                new_do_charging = False
            else:
                new_do_charging = True

        if currently_charging != new_do_charging:
            self.set_charging(vehicle, new_do_charging)
        if new_do_charging:
            new_amperage = max(new_amperage, self.min_amperage)
            if new_amperage != current_amperage:
                self.set_charge_speed(vehicle, new_amperage)
        return ChargeControlResult(new_do_charging, soc_min_reached, soc_limit_reached)

if __name__ == '__main__':
    with open("options.json", "r") as fp:
        options = json.load(fp)

    twc_vitals_url = 'http://' + options['TWC_IP_ADDRESS']+ '/api/1/vitals'
    poll_time = int(options['POLL_TIME'])

    tesla_api = TeslaApi(options['TESLA_MAIL'], options['TESLA_TOKEN'])
    historic_data = HistoricData()
    charge_control = ChargeControl(tesla_api, options)
    adapt_charge_speed = True

    def signal_handler(signal, frame):
        tesla_api.close()
        print("\nprogram exiting gracefully")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    while True:
        twc_vitals = json.loads(requests.get(twc_vitals_url).content.decode('UTF-8'))

        vehicle_connected = twc_vitals['vehicle_connected']
        battery_data = tesla_api.call('battery_data')
        grid_power = int(battery_data['power_reading'][0]['grid_power'])
        solar_power = int(battery_data['power_reading'][0]['solar_power'])

        # try to adapt the charge speed if the vehicle is connected and we should adapt the charge speed
        if vehicle_connected and adapt_charge_speed:
            log("vehicle is connected, adding current grid power to history")
            power_history = historic_data.add(grid_power)
            if (len(power_history) > 0):
                log("trying to adapt charging speed")
                result = charge_control.update_charge_speed(np.array(power_history))
                # disable charge adaption when the SOC limit is reached
                if not result.vehicle_is_charging and result.soc_limit_reached:
                    log("vehicle is no longer charging and car SOC limit has been reached, stop polling")
                    adapt_charge_speed = False
                # disable charge adaption when the min SOC is reached and we have no solar
                if not result.vehicle_is_charging and result.soc_min_reached and solar_power == 0:
                    log("vehicle is no longer charging, min SOC limit has been reached and solar power is out, stop polling")
                    adapt_charge_speed = False
        # re-enable charging when we get solar input and are still connected
        elif vehicle_connected and not adapt_charge_speed and solar_power > 0:
            log("vehicle connected and sleeping, now getting solar power again")
            adapt_charge_speed = True
        # re-enable charging when the vehicle is connected again (now possibly with a lower SOC)
        elif not vehicle_connected:
            log("vehicle not connected, enable adapting charge speed again")
            adapt_charge_speed = True

        time.sleep(poll_time)
