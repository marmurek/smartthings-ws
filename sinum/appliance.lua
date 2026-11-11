-- Sinum custom device for one appliance served by smartthings-ws.
--
-- State arrives over the WebSocket component `ws`: the full list on connect,
-- then change reports. Commands go out over the same socket. The state is
-- kept in utils.c, the script's own storage, which survives a rebuild of the
-- interpreter, so the device shows it at once. Reports sent during a rebuild
-- are lost and a rebuild while the socket stays connected delivers no list,
-- so the HTTP client component `api` reads the state once after each rebuild.
-- The variable component `appliance` holds the name the appliance has in
-- smartthings-ws; `warnings` holds the warnings whose text depends on the
-- state, so they can be removed after a restart as well.
--
-- Other scripts read the state of every appliance whose device is online
-- from the global storage, e.g. utils.C.smartthings_ws.fridge.door_open.
--
-- Every device uses this script; the elements differ by appliance kind, so
-- each element is looked up once and skipped when the device does not have it.

local ELEMENTS <const> = {
  "summary",
  "progress",
  "program",
  "remote",
  "lock",
  "energy",
  "doors",
  "temperature",
  "timing",
  "steam",
  "maintenance",
  "dosing",
  "fridge_modes",
  "self_check",
  "power",
  "start",
  "pause",
  "stop",
  "fridge_target",
  "freezer_target",
  "rapid_cooling",
  "rapid_freezing",
  "water_temperature",
  "spin_level",
  "rinse_cycles",
  "dry_level",
  "dry_time",
  "wrinkle_prevent",
  "delay",
  "sound",
  "lamp",
  "fast_preheat",
  "energy_saving",
  "door_alarm",
  "cook_mode",
  "cook_temperature",
  "cook_time",
  "cook_start",
}

-- Seconds between reads of the state over HTTP until one succeeds after a rebuild.
local FETCH_RETRY <const> = 30

local JOBS <const> = {
  Weightsensing = "Ważenie",
  Wash = "Pranie",
  Rinse = "Płukanie",
  Spin = "Wirowanie",
  AIDrying = "Suszenie AI",
  Drying = "Suszenie",
  Cooling = "Schładzanie",
  InternalCare = "Pielęgnacja bębna",
  Finish = "Zakończono",
}

local MODES <const> = {
  UpperAirFry = "Air Fry",
  UpperConvection = "Termoobieg",
  UpperTopConvection = "Termoobieg z górną grzałką",
  UpperLargeGrill = "Grill",
  UpperAutocook = "Program automatyczny",
  Convection = "Termoobieg",
  TopHeatPluseConvection = "Termoobieg z górną grzałką",
  BottomHeatPluseConvection = "Termoobieg z dolną grzałką",
  Conventional = "Grzanie góra-dół",
  LargeGrill = "Duży grill",
  SmallGrill = "Mały grill",
  FanGrill = "Grill z termoobiegiem",
  Bottom = "Grzałka dolna",
  EcoConvection = "Termoobieg Eco",
  ProRoasting = "Pro-Roasting",
  PlateWarm = "Podgrzewanie talerzy",
  Defrost = "Rozmrażanie",
  AirSousvide = "Air Sous Vide",
  SteamConvection = "Termoobieg z parą",
  SteamTopConvection = "Termoobieg z górną grzałką i parą",
  SteamBottomConvection = "Termoobieg z dolną grzałką i parą",
  MicroWave = "Mikrofale",
  Autocook = "Program automatyczny",
  KeepWarm = "Podtrzymanie ciepła",
  Deodorization = "Odświeżanie",
  SteamClean = "Czyszczenie parą",
}

-- Laundry programme names by course table and code, for the programmes the
-- washer and dryer offer. The same code names another programme in another
-- table. Names from the LocalThings translations (MIT License, Copyright (c)
-- 2026 Marc Billow, https://github.com/mbillow/localthings).
local COURSES <const> = {
  Table_02 = {
    ["1B"] = "Bawełna",
    ["1C"] = "Eco 40-60",
    ["1D"] = "Super szybki",
    ["1E"] = "Szybkie pranie 15'",
    ["20"] = "Higieniczna para",
    ["21"] = "Tkaniny kolorowe",
    ["22"] = "Wełna",
    ["23"] = "Odzież wierzchnia",
    ["24"] = "Pościel",
    ["25"] = "Syntetyki",
    ["26"] = "Delikatne",
    ["27"] = "Płukanie + wirowanie",
    ["28"] = "Odpompowanie/wirowanie",
    ["29"] = "Czyszczenie bębna+",
    ["2A"] = "Jeansy",
    ["2B"] = "Pranie optymalne",
    ["2D"] = "Ciche pranie",
    ["2E"] = "Dziecięce",
    ["2F"] = "Odzież sportowa",
    ["30"] = "Pochmurny dzień",
    ["32"] = "Koszule",
    ["33"] = "Ręczniki",
    ["8F"] = "Intensywne pranie na zimno",
    ["96"] = "Mniej włókien",
  },
  Table_03 = {
    ["16"] = "Bawełna",
    ["17"] = "Super szybki",
    ["18"] = "Syntetyki",
    ["19"] = "Delikatne",
    ["1A"] = "Wełna",
    ["1B"] = "Pościel",
    ["1C"] = "Koszule",
    ["1D"] = "Ręczniki",
    ["1E"] = "Odzież wierzchnia",
    ["20"] = "Do prasowania",
    ["21"] = "Higiena",
    ["22"] = "Ciche suszenie",
    ["23"] = "Suszenie 35'",
    ["24"] = "Zimne powietrze",
    ["25"] = "Ciepłe powietrze",
    ["27"] = "Czas suszenia",
    ["29"] = "Suszenie AI",
    ["2B"] = "Osuszanie bębna",
    ["4C"] = "Odświeżanie",
  },
}

local DRY_LEVELS <const> = { Damp = "wilgotne", Less = "lekkie", Normal = "normalne", More = "mocne" }

local WATER_TEMPERATURES <const> = { Cold = "zimna woda" }

local SPIN_LEVELS <const> = { NoSpin = "bez wirowania", RinseHold = "stop z wodą" }

local ZONES <const> = { freezer = "zamrażarka", fridge = "chłodziarka" }

-- Grammatical gender of the appliance names, for "ready" and "switched off".
local MASCULINE <const> = { oven = true }

-- Warnings with a fixed text, shown while the condition holds.
local WARNINGS <const> = {
  {
    "Dostępna aktualizacja oprogramowania",
    function(st)
      return st.firmware_update_available == true
    end,
  },
  {
    "Kończy się detergent w automatycznym dozowniku",
    function(st)
      return st.detergent_low == true
    end,
  },
  {
    "Kończy się płyn do płukania w automatycznym dozowniku",
    function(st)
      return st.softener_low == true
    end,
  },
  {
    "Zalecane czyszczenie bębna",
    function(st)
      return st.drum_clean_due_in == 0
    end,
  },
  {
    "Zalecane odkamienianie",
    function(st)
      return type(st.descale_alarm) == "string" and st.descale_alarm ~= "Normal"
    end,
  },
  {
    "Odkamienianie: wlej świeżą wodę",
    function(st)
      return st.descale_new_water_alarm == true
    end,
  },
  {
    "Odkamienianie: opróżnij zbiornik",
    function(st)
      return st.descale_empty_water_alarm == true
    end,
  },
  {
    "Opróżnij układ parowy",
    function(st)
      return st.drain_required == true
    end,
  },
}

function CustomDevice:onRebuildInstance()
  self.ws = self:getComponent("ws")
  self.api = self:getComponent("api")
  self.name = self:getComponent("appliance"):getValue()
  self.warningStore = self:getComponent("warnings")
  self.elements = {}
  for _, name in ipairs(ELEMENTS) do
    local ok, element = pcall(self.getElement, self, name)
    if ok then
      self.elements[name] = element
    end
  end
  self.state = utils.c.state
  -- Whether the state was received since the rebuild.
  self.current = false
  self.fetchedAt = nil
end

function CustomDevice:setState(st)
  self.state = st
  self.current = true
  utils.c.state = st
  self:render()
end

function CustomDevice:onInit(reason)
  self:render()
end

function CustomDevice:onEvent(event)
  self.ws:onConnected(function()
    self:render()
  end)

  self.ws:onDisconnected(function()
    self:render()
  end)

  self.ws:onMessage(function(payload)
    self:onSocketMessage(payload)
  end)

  self.api:onMessage(function(status, body)
    self:onStateResponse(status, body)
  end)

  if not self.current and self.ws:isConnected() then
    self:fetchState()
  end

  -- A lost socket emits no event while the server cannot be reached.
  if event.type == "minute_changed" then
    self:render()
  end
end

-- ---------------------------------------------------------------------------
-- State from smartthings-ws
-- ---------------------------------------------------------------------------

function CustomDevice:fetchState()
  if self.fetchedAt ~= nil and os.time() - self.fetchedAt < FETCH_RETRY then
    return
  end
  self.fetchedAt = os.time()
  self.api:GET("/appliances/" .. self.name):header("Accept", "application/json"):send()
end

function CustomDevice:onStateResponse(status, body)
  if status ~= 200 then
    utils:printf("Reading %s failed with status %d", self.name, status)
    return
  end
  local ok, data = pcall(JSON.decode, JSON, body)
  if ok and type(data) == "table" then
    self:setState(data)
  end
end

function CustomDevice:onSocketMessage(payload)
  local ok, message = pcall(JSON.decode, JSON, payload)
  if not ok or type(message) ~= "table" then
    return
  end

  if message.type == "list" and type(message.data) == "table" then
    for _, appliance in pairs(message.data) do
      if type(appliance) == "table" and appliance.name == self.name then
        self:setState(appliance)
      end
    end
  elseif message.name ~= self.name then
    return
  elseif message.type == "report" and self.state ~= nil and type(message.data) == "table" then
    -- A field that became null has no "new" key, which clears it here.
    for field, change in pairs(message.data) do
      if type(change) == "table" then
        self.state[field] = change.new
      end
    end
    self:render()
  elseif message.type == "error" then
    utils:printf("Command %s failed: %s", tostring(message.message_id), tostring(message.message))
    self:commandFailed(message.message)
  elseif message.type == "applied" or message.type == "not_changed" then
    utils:printf("Command %s: %s", tostring(message.message_id), message.type)
  end
end

function CustomDevice:commandFailed(reason)
  local text
  if self.state ~= nil and self.state.remote_control == false then
    text = "Włącz zdalne sterowanie na panelu urządzenia"
  else
    text = "Polecenie nie zostało wykonane: " .. tostring(reason)
  end
  toast:failure():text(text):show()
  -- Put back the control the user changed; the appliance did not change.
  self:render()
end

-- ---------------------------------------------------------------------------
-- Commands
-- ---------------------------------------------------------------------------

function CustomDevice:send(data)
  if not self:isOnline() then
    toast:failure():text("Urządzenie jest niedostępne"):show()
    self:render()
    return
  end
  utils.c.messageId = (utils.c.messageId or 0) + 1
  self.ws:send(JSON:encode({ type = "update", name = self.name, message_id = utils.c.messageId, data = data }))
end

local function rounded(value)
  return math.floor(tonumber(value) + 0.5)
end

function CustomDevice:onPower(value)
  self:send({ power = value })
end

function CustomDevice:onStart()
  self:send({ operation = "start" })
end

function CustomDevice:onPause()
  self:send({ operation = "pause" })
end

function CustomDevice:onStop()
  self:send({ operation = "stop" })
end

function CustomDevice:onFridgeTarget(value)
  self:send({ fridge_target = rounded(value) })
end

function CustomDevice:onFreezerTarget(value)
  self:send({ freezer_target = rounded(value) })
end

function CustomDevice:onRapidCooling(value)
  self:send({ rapid_cooling = value })
end

function CustomDevice:onRapidFreezing(value)
  self:send({ rapid_freezing = value })
end

function CustomDevice:onSound(value)
  self:send({ sound = value })
end

function CustomDevice:onLamp(value)
  self:send({ lamp = value })
end

function CustomDevice:onFastPreheat(value)
  self:send({ fast_preheat = value })
end

function CustomDevice:onWrinklePrevent(value)
  self:send({ wrinkle_prevent = value })
end

-- Combo box values are the values smartthings-ws reports, as strings.
function CustomDevice:onWaterTemperature(value)
  self:send({ water_temperature = value })
end

function CustomDevice:onSpinLevel(value)
  self:send({ spin_level = value })
end

function CustomDevice:onRinseCycles(value)
  self:send({ rinse_cycles = rounded(value) })
end

function CustomDevice:onDryLevel(value)
  self:send({ dry_level = value })
end

function CustomDevice:onDryTime(value)
  self:send({ dry_time_minutes = rounded(value) })
end

function CustomDevice:onDelay(value)
  self:send({ delay_finish_minutes = rounded(value) })
end

function CustomDevice:onEnergySaving(value)
  self:send({ energy_saving_level = rounded(value) })
end

function CustomDevice:onDoorAlarm(value)
  self:send({ door_alarm_volume = rounded(value) })
end

-- The cook the remote start sends, kept in utils.c until it is sent. A mode
-- the oven does not offer now is replaced by the default one.
function CustomDevice:cookChoice(st)
  local modes = {}
  for _, mode in ipairs(type(st.cook_modes) == "table" and st.cook_modes or {}) do
    modes[mode.mode] = mode
  end
  local choice = utils.c.cook
  if type(choice) ~= "table" or modes[choice.mode] == nil then
    local spec = modes[st.default_mode] or (type(st.cook_modes) == "table" and st.cook_modes[1]) or nil
    if spec == nil then
      return nil, nil
    end
    choice = { mode = spec.mode, temperature = spec.temperature_default, minutes = spec.minutes_default }
    utils.c.cook = choice
  end
  return choice, modes[choice.mode]
end

function CustomDevice:onCookMode(value)
  local st = self.state or {}
  for _, mode in ipairs(type(st.cook_modes) == "table" and st.cook_modes or {}) do
    if mode.mode == value then
      utils.c.cook = { mode = value, temperature = mode.temperature_default, minutes = mode.minutes_default }
    end
  end
  self:render()
end

function CustomDevice:onCookTemperature(value)
  local choice, spec = self:cookChoice(self.state or {})
  if choice ~= nil then
    local step = spec.temperature_step
    choice.temperature = spec.temperature_min + rounded((tonumber(value) - spec.temperature_min) / step) * step
  end
  self:render()
end

function CustomDevice:onCookTime(value)
  local choice = self:cookChoice(self.state or {})
  if choice ~= nil then
    choice.minutes = rounded(value)
  end
  self:render()
end

function CustomDevice:onCookStart()
  local choice = self:cookChoice(self.state or {})
  if choice == nil then
    toast:failure():text("Urządzenie nie oferuje zdalnego startu"):show()
    return
  end
  self:send({ cook = { mode = choice.mode, temperature = choice.temperature, minutes = choice.minutes } })
end

-- Commands for scenes and automations, e.g. virtual[ID]:call("start").
function CustomDevice:onCommand(command, arg)
  if command == "start" or command == "pause" or command == "stop" then
    self:send({ operation = command })
  elseif command == "power_on" or command == "power_off" then
    self:send({ power = command == "power_on" })
  elseif command == "set_fridge_target" and type(arg) == "number" then
    self:send({ fridge_target = rounded(arg) })
  elseif command == "set_freezer_target" and type(arg) == "number" then
    self:send({ freezer_target = rounded(arg) })
  elseif command == "set_rapid_cooling" and type(arg) == "boolean" then
    self:send({ rapid_cooling = arg })
  elseif command == "set_rapid_freezing" and type(arg) == "boolean" then
    self:send({ rapid_freezing = arg })
  elseif command == "set_sound" and type(arg) == "boolean" then
    self:send({ sound = arg })
  elseif command == "set_lamp" and type(arg) == "boolean" then
    self:send({ lamp = arg })
  elseif command == "set_delay" and type(arg) == "number" then
    self:send({ delay_finish_minutes = rounded(arg) })
  elseif command == "cook" and type(arg) == "table" and type(arg.mode) == "string" then
    -- e.g. virtual[ID]:call("cook", { mode = "UpperConvection", temperature = 180, minutes = 45 })
    self:send({ cook = { mode = arg.mode, temperature = arg.temperature, minutes = arg.minutes } })
  else
    utils:printf("Unknown command %s", tostring(command))
  end
end

-- ---------------------------------------------------------------------------
-- Presentation
-- ---------------------------------------------------------------------------

function CustomDevice:isOnline()
  return self.ws:isConnected() and self.state ~= nil and self.state.available == true
end

local function temperature(value)
  if type(value) ~= "number" then
    return "–"
  end
  return string.format("%.0f°C", value)
end

local function duration(minutes)
  if type(minutes) ~= "number" then
    return nil
  end
  if minutes < 60 then
    return string.format("%d min", minutes)
  end
  return string.format("%d h %02d min", minutes // 60, minutes % 60)
end

local function kwh(value)
  return type(value) == "number" and string.format("%.1f kWh", value) or nil
end

-- Explicit parameters: the interpreter has no `select`, and a table
-- constructor with nil entries has no reliable length.
local function joined(a, b, c, d)
  local present = {}
  for _, part in ipairs({ a or "", b or "", c or "", d or "" }) do
    if part ~= "" then
      present[#present + 1] = part
    end
  end
  return table.concat(present, " · ")
end

local function capitalized(text)
  return (text:gsub("^%l", string.upper))
end

-- "2026-11-03T15:34:56" as "03.11.2026".
local function date(iso)
  if type(iso) ~= "string" then
    return nil
  end
  local year, month, day = iso:match("^(%d+)-(%d+)-(%d+)")
  return year and string.format("%s.%s.%s", day, month, year) or nil
end

function CustomDevice:summary(st)
  if not self.ws:isConnected() then
    return "Brak połączenia z smartthings-ws"
  end
  if st == nil then
    return "Odczytywanie…"
  end
  if st.available ~= true then
    return "Urządzenie nie odpowiada"
  end

  if st.kind == "fridge" then
    return string.format(
      "Chłodziarka %s · Zamrażarka %s",
      temperature(st.fridge_temperature),
      temperature(st.freezer_temperature)
    )
  end

  local masculine = MASCULINE[st.kind]
  local remaining = st.remaining_minutes and ("zostało " .. duration(st.remaining_minutes)) or nil
  local progress = type(st.progress) == "number" and string.format("%d%%", st.progress) or nil
  local activity = JOBS[st.job] or MODES[st.oven_mode] or "Praca"

  if st.machine_state == "running" then
    return joined(activity, progress, remaining)
  elseif st.machine_state == "paused" then
    return joined("Wstrzymano", activity, progress, remaining)
  elseif st.power == false then
    return masculine and "Wyłączony" or "Wyłączona"
  end
  local ready = masculine and "Gotowy" or "Gotowa"
  if st.kind == "washer" or st.kind == "dryer" then
    return joined(
      ready,
      st.remaining_minutes and st.remaining_minutes > 0 and ("program " .. duration(st.remaining_minutes))
    )
  end
  return ready
end

function CustomDevice:courseName(st)
  if st.course == nil then
    return nil
  end
  local names = COURSES[st.course_table]
  return names and names[string.upper(st.course)] or ("Program " .. st.course)
end

function CustomDevice:program(st)
  if st.kind == "washer" then
    local water = WATER_TEMPERATURES[st.water_temperature] or (st.water_temperature and st.water_temperature .. "°C")
    local spin = SPIN_LEVELS[st.spin_level] or (st.spin_level and st.spin_level .. " obr/min")
    local rinses = type(st.rinse_cycles) == "number" and string.format("płukania: %d", st.rinse_cycles) or nil
    return joined(self:courseName(st), water, spin, rinses)
  elseif st.kind == "dryer" then
    local level = DRY_LEVELS[st.dry_level] and ("suszenie " .. DRY_LEVELS[st.dry_level]) or nil
    local time = type(st.dry_time_minutes) == "number" and st.dry_time_minutes > 0 and duration(st.dry_time_minutes)
    return joined(self:courseName(st), level, time, st.wrinkle_prevent and "antyzagniecenia")
  end
  return ""
end

function CustomDevice:doors(st)
  if st.kind == "fridge" then
    local open = {}
    if st.fridge_door_open then
      open[#open + 1] = "chłodziarki"
    end
    if st.freezer_door_open then
      open[#open + 1] = "zamrażarki"
    end
    if #open > 0 then
      return "Otwarte drzwi " .. table.concat(open, " i ")
    end
    return "Drzwi zamknięte"
  end
  if st.door_open == nil then
    return ""
  end
  return st.door_open and "Drzwi otwarte" or "Drzwi zamknięte"
end

function CustomDevice:energy(st)
  local draw = type(st.power_w) == "number" and string.format("Pobór %.0f W", st.power_w) or nil
  local water = type(st.water_liters) == "number" and string.format("woda %.0f l", st.water_liters) or nil
  local saved = kwh(st.energy_saved_kwh)
  return capitalized(
    joined(
      draw,
      kwh(st.energy_kwh) and ("zużycie " .. kwh(st.energy_kwh)),
      water,
      saved and ("zaoszczędzono " .. saved)
    )
  )
end

function CustomDevice:temperatureText(st)
  if type(st.oven_target) ~= "number" or st.oven_target <= 0 then
    return ""
  end
  return string.format("Temperatura %s, zadana %s", temperature(st.oven_temperature), temperature(st.oven_target))
end

function CustomDevice:timing(st)
  local elapsed = type(st.elapsed_minutes) == "number"
    and st.elapsed_minutes > 0
    and ("Czas pracy " .. duration(st.elapsed_minutes))
  local timer = nil
  if st.timer_state ~= nil and st.timer_state ~= "Ready" then
    timer = joined("minutnik " .. string.lower(st.timer_state), st.timer_remaining and tostring(st.timer_remaining))
  end
  return capitalized(joined(elapsed, timer))
end

function CustomDevice:steam(st)
  if st.steam_generator_level == nil then
    return ""
  end
  local level = st.steam_generator_level == "Empty" and "pusty" or string.lower(st.steam_generator_level)
  local inlet = st.water_inlet == "Closed" and "dopływ wody zamknięty"
    or (st.water_inlet and ("dopływ wody: " .. string.lower(st.water_inlet)))
  local descale = st.descale_state and st.descale_state ~= "Standby" and ("odkamienianie: " .. st.descale_state)
  return joined("Zbiornik pary " .. level, inlet, descale)
end

function CustomDevice:maintenance(st)
  if st.drum_clean_due_in == nil and st.drum_clean_last == nil then
    return ""
  end
  local due = nil
  if type(st.drum_clean_due_in) == "number" then
    local cycles = st.kind == "washer" and "prań" or "cykli"
    due = st.drum_clean_due_in > 0 and string.format("Czyszczenie bębna za %d %s", st.drum_clean_due_in, cycles)
      or "Czyszczenie bębna zalecane"
  end
  local last = date(st.drum_clean_last)
  return capitalized(joined(due, last and ("ostatnie czyszczenie " .. last)))
end

function CustomDevice:dosing(st)
  if st.detergent_dose == nil and st.softener_dose == nil then
    return ""
  end
  return joined(
    st.detergent_dose and string.format("Dozowanie detergentu: %d", st.detergent_dose),
    st.softener_dose and string.format("płynu: %d", st.softener_dose)
  )
end

function CustomDevice:fridgeModes(st)
  local vacation = st.vacation_mode == true and "Tryb wakacyjny włączony"
    or (st.vacation_mode == false and "Tryb wakacyjny wyłączony")
  local zone = st.convertible_zone and ("komora zamienna: " .. (ZONES[st.convertible_zone] or st.convertible_zone))
  return joined(vacation, zone)
end

function CustomDevice:selfCheck(st)
  if st.self_check_result == nil then
    return ""
  end
  local errors = type(st.self_check_errors) == "table"
    and #st.self_check_errors > 0
    and table.concat(st.self_check_errors, ", ")
  return joined(
    "Autodiagnostyka: " .. (st.self_check_result == "Success" and "bez usterek" or st.self_check_result),
    errors
  )
end

local function startable(st)
  return type(st.cook_modes) == "table" and #st.cook_modes > 0
end

-- The panel setting matters while the appliance is on, and for an oven that
-- can be started remotely also while it is off.
function CustomDevice:remote(st)
  if st.power == false and not startable(st) then
    return ""
  end
  if st.remote_control == false then
    return "Zdalne sterowanie wyłączone na panelu urządzenia"
  elseif st.remote_control == true then
    return "Zdalne sterowanie włączone"
  end
  return ""
end

-- Warnings whose text depends on the state: one per firing alarm and the
-- self check errors.
function CustomDevice:dynamicWarnings(st)
  local texts = {}
  if type(st.alarms) == "table" then
    for _, code in ipairs(st.alarms) do
      texts[#texts + 1] = "Alarm urządzenia: " .. code
    end
  end
  if type(st.self_check_errors) == "table" and #st.self_check_errors > 0 then
    texts[#texts + 1] = "Autodiagnostyka: " .. table.concat(st.self_check_errors, ", ")
  end
  return texts
end

function CustomDevice:renderWarnings(st)
  for _, warning in ipairs(WARNINGS) do
    self:updateWarning(warning[1], nil, warning[2](st))
  end

  local wanted = {}
  for _, text in ipairs(self:dynamicWarnings(st)) do
    wanted[text] = true
  end

  local ok, shown = pcall(JSON.decode, JSON, self.warningStore:getValue())
  if not ok or type(shown) ~= "table" then
    shown = {}
  end
  for _, text in ipairs(shown) do
    if not wanted[text] then
      self:updateWarning(text, nil, false)
    end
  end

  local keep = {}
  for text in pairs(wanted) do
    self:updateWarning(text, nil, true)
    keep[#keep + 1] = text
  end
  table.sort(keep)
  local encoded = JSON:encode(keep)
  if encoded ~= self.warningStore:getValue() then
    self.warningStore:setValue(encoded, true):save(true)
  end
end

-- Element writes go out only when the value differs, so a report changing one
-- field does not rewrite every element.
local function put(element, property, value)
  if element:getValue(property) ~= value then
    element:setValue(property, value, true)
  end
end

function CustomDevice:setText(name, text)
  local element = self.elements[name]
  if element == nil then
    return
  end
  -- An empty text hides the element instead of leaving a blank line.
  put(element, "visibility", text ~= "" and "visible" or "hidden_adjust")
  if text ~= "" then
    put(element, "value", text)
  end
end

function CustomDevice:setControl(name, enabled, value)
  local element = self.elements[name]
  if element == nil then
    return
  end
  put(element, "enabled", enabled)
  if value == nil then
    return
  end
  local kind = element:getValue("type")
  if kind == "slider" then
    value = utils.math:clamp(element:getValue("minimum"), element:getValue("maximum"), value)
  elseif kind == "combo_box" then
    -- A whole number decoded as a float would print as "1.0".
    value = tostring(math.type(value) == "float" and math.tointeger(value) or value)
    if element:getValue("value") ~= value then
      -- An error here would recur on every report and get the device banned.
      local ok, err = pcall(function()
        self:addMissingOption(name, element, value)
        element:setValue("value", value, true)
      end)
      if not ok then
        utils:printf("Cannot show %s = %s: %s", name, value, tostring(err))
      end
    end
    return
  end
  put(element, "value", value)
end

local function delayLabel(minutes)
  return minutes == 0 and "Bez opóźnienia" or ("Koniec za " .. duration(minutes))
end

-- Labels of the values the options of a combo box did not have when the device
-- was built, e.g. a delay set on the appliance's panel.
local OPTION_LABELS <const> = {
  water_temperature = function(v)
    return v == "Cold" and "Zimna woda" or (v .. "°C")
  end,
  spin_level = function(v)
    return SPIN_LEVELS[v] and capitalized(SPIN_LEVELS[v]) or (v .. " obr/min")
  end,
  dry_level = function(v)
    return DRY_LEVELS[v] and capitalized(DRY_LEVELS[v]) or v
  end,
  dry_time = function(v)
    return tonumber(v) == 0 and "Do poziomu suszenia" or (duration(tonumber(v)) or v)
  end,
  delay = function(v)
    return tonumber(v) and delayLabel(tonumber(v)) or v
  end,
  cook_mode = function(v)
    return MODES[v] or v
  end,
  cook_time = function(v)
    return tonumber(v) and duration(tonumber(v)) or v
  end,
  energy_saving = function(v)
    return "Poziom " .. v
  end,
  door_alarm = function(v)
    return "Głośność " .. v
  end,
}

function CustomDevice:addMissingOption(name, element, value)
  local options = element:getValue("available_options")
  if type(options) == "table" then
    for _, option in pairs(options) do
      if type(option) == "table" and option.value == value then
        return
      end
    end
  end
  local label = OPTION_LABELS[name] and OPTION_LABELS[name](value) or value
  element:call("add_option", { label, value }, true)
end

-- Follow the setpoint range the fridge reports. A bound may only move past
-- the other one once the other has moved, so the order depends on the direction.
function CustomDevice:setRange(name, range)
  local element = self.elements[name]
  if element == nil or type(range) ~= "table" or type(range[1]) ~= "number" or type(range[2]) ~= "number" then
    return
  end
  if range[1] > element:getValue("maximum") then
    put(element, "maximum", range[2])
    put(element, "minimum", range[1])
  else
    put(element, "minimum", range[1])
    put(element, "maximum", range[2])
  end
end

function CustomDevice:render()
  local online = self:isOnline()
  local status = online and "online" or "offline"
  if status ~= self.status then
    self.status = status
    self:setValue("status", status)
  end

  self:setText("summary", self:summary(self.state))

  local st = self.state or {}
  local running = st.machine_state == "running"
  local active = running or st.machine_state == "paused"

  if self.elements.progress ~= nil then
    local progress = active and type(st.progress) == "number" and st.progress or 0
    put(self.elements.progress, "visibility", active and "visible" or "hidden_adjust")
    put(self.elements.progress, "value", utils.math:clamp(0, 100, progress))
  end

  if self.state ~= nil then
    self:setText("program", self:program(st))
    self:setText("remote", self:remote(st))
    self:setText("lock", st.child_lock == true and "Blokada rodzicielska włączona" or "")
    self:setText("energy", self:energy(st))
    self:setText("doors", self:doors(st))
    self:setText("temperature", self:temperatureText(st))
    self:setText("timing", self:timing(st))
    self:setText("steam", self:steam(st))
    self:setText("maintenance", self:maintenance(st))
    self:setText("dosing", self:dosing(st))
    self:setText("fridge_modes", self:fridgeModes(st))
    self:setText("self_check", self:selfCheck(st))
    self:setRange("fridge_target", st.fridge_range)
    self:setRange("freezer_target", st.freezer_range)
    if st.available == true then
      self:renderWarnings(st)
    end
  end

  -- Laundry and ovens run, pause and set up a programme only with Remote
  -- Control enabled on their panel; stopping, the lamp and the sounds do not
  -- need it. The fridge does not report it.
  local controllable = online and st.remote_control ~= false
  -- Settings of the selected programme can change only before it starts.
  local idle = controllable and not active

  self:setControl("power", controllable, st.power)
  self:setControl("start", controllable and not running)
  self:setControl("pause", controllable and running)
  self:setControl("stop", online and active)
  self:setControl("fridge_target", online, st.fridge_target)
  self:setControl("freezer_target", online, st.freezer_target)
  self:setControl("rapid_cooling", online, st.rapid_cooling)
  self:setControl("rapid_freezing", online, st.rapid_freezing)
  self:setControl("sound", online, st.sound)
  self:setControl("lamp", online, st.lamp)
  self:setControl("fast_preheat", online, st.fast_preheat)
  self:setControl("energy_saving", online, st.energy_saving_level)
  self:setControl("door_alarm", online, st.door_alarm_volume)
  self:setControl("water_temperature", idle, st.water_temperature)
  self:setControl("spin_level", idle, st.spin_level)
  self:setControl("rinse_cycles", idle, st.rinse_cycles)
  self:setControl("dry_level", idle, st.dry_level)
  self:setControl("dry_time", idle, st.dry_time_minutes)
  self:setControl("wrinkle_prevent", idle, st.wrinkle_prevent)
  self:setControl("delay", idle, st.delay_finish_minutes)
  self:renderCook(st, online)
  self:share(online)
end

function CustomDevice:renderCook(st, online)
  local element = self.elements.cook_mode
  if element == nil then
    return
  end
  -- The modes on offer follow the oven's divider.
  for _, mode in ipairs(type(st.cook_modes) == "table" and st.cook_modes or {}) do
    pcall(self.addMissingOption, self, "cook_mode", element, mode.mode)
  end
  local choice, spec = self:cookChoice(st)
  local ready = online
    and spec ~= nil
    and st.remote_control == true
    and st.machine_state == "idle"
    and st.oven_mode == nil
  self:setControl("cook_mode", online and spec ~= nil, choice and choice.mode)
  if spec ~= nil then
    self:setRange("cook_temperature", { spec.temperature_min, spec.temperature_max })
  end
  self:setControl("cook_temperature", ready, choice and choice.temperature)
  self:setControl("cook_time", ready, choice and choice.minutes)
  self:setControl("cook_start", ready)
end

function CustomDevice:share(online)
  if utils.C == nil or self.name == nil then
    return
  end
  local shared = utils.C.smartthings_ws or {}
  shared[self.name] = online and self.state or nil
  utils.C.smartthings_ws = shared
end
