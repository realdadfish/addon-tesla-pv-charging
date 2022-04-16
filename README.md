# Description
Script for pv excess charging, based on https://github.com/KastB/addon-tesla-pv-charging.
  
The basic python script that controls the charge speed via the tesla api and gets its information via Tesla API (Vehicle and Battery / Gateway) as well as the HTTP API of the Tesla Wall Conncetor.

Feel free to create issues / fork, change and create merge-requests.

# Properties
The step-size for 400V is ~690W (230V*3*1A) unless you use less than 3 phases. 
 
*There is a control loop which:*
- stops charging below a certain amperage (the car has 500W consumption, and it becomes too inefficient to charge with low charge speeds => stop charging and go to sleep during night)
- charges as fast as possible below a certain SOC (configurable)
- tries to prevent feed-in below a certain SOC (configurable)
- tries to prevent grid consumption above a certain SOC (configurable)
- does not change settings if max-SOC is 100% or max-charge-speed is higher than a certain speed (due to delays you should first set the do-not-interfere SOC in your app, and change it back later if you wish) => you can control the behaviour with the Tesla app, when you go on a trip.

*Caveats:*
- some parameters might not yet be exposed in the plugin (e.g. effective voltage (just 2 phases, US-grid), ?)
- This works only for Teslas, we must rely on an unofficial api, and at the moment only for one car (might change soon though)
- I limited the rate to 30s and the car needs a few seconds to adapt the charge speed. So we consume 700-1000W in the "prevent-feed-in-phase"
