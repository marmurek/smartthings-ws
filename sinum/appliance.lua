-- Sinum custom device for one appliance served by smartthings-ws.
--
-- State arrives over the WebSocket component `ws`: the full list on connect,
-- then change reports. Commands go out over the same socket. The HTTP client
-- component `api` reads the state once when the script has none, which
-- happens after every rebuild of the interpreter while the socket stays
-- connected. The variable component `appliance` holds the name the
-- appliance has in smartthings-ws.
--
-- Every device uses this script; the elements differ by appliance kind, so
-- each element is looked up once and skipped when the device does not have it.

local ELEMENTS <const> = {
  "summary",
  "progress",
  "program",
  "remote",
  "energy",
  "doors",
  "temperature",
  "power",
  "start",
  "pause",
  "stop",
  "fridge_target",
  "freezer_target",
  "rapid_cooling",
  "rapid_freezing",
}

-- Seconds between reads of the state over HTTP while the script has none.
local FETCH_RETRY <const> = 30

local JOBS <const> = {
  Weightsensing = "Ważenie",
  Wash = "Pranie",
  Rinse = "Płukanie",
  Spin = "Wirowanie",
  AIDrying = "Suszenie AI",
  Drying = "Suszenie",
  Cooling = "Schładzanie",
  Finish = "Zakończono",
}

local MODES <const> = {
  UpperAirFry = "Air Fry",
  UpperConvection = "Termoobieg",
  UpperTopConvection = "Termoobieg z górną grzałką",
  UpperLargeGrill = "Grill",
  UpperAutocook = "Program automatyczny",
  MicroWave = "Mikrofale",
  Autocook = "Program automatyczny",
  KeepWarm = "Podtrzymanie ciepła",
  Deodorization = "Odświeżanie",
  SteamClean = "Czyszczenie parą",
}

local DRY_LEVELS <const> = { Damp = "wilgotne", Less = "lekkie", Normal = "normalne", More = "mocne" }

local WATER_TEMPERATURES <const> = { Cold = "zimna woda" }

local SPIN_LEVELS <const> = { NoSpin = "bez wirowania", RinseHold = "stop z wodą" }

-- Grammatical gender of the appliance names, for "ready" and "switched off".
local MASCULINE <const> = { oven = true }

function CustomDevice:onRebuildInstance()
  self.ws = self:getComponent("ws")
  self.api = self:getComponent("api")
  self.name = self:getComponent("appliance"):getValue()
  self.elements = {}
  for _, name in ipairs(ELEMENTS) do
    local ok, element = pcall(self.getElement, self, name)
    if ok then
      self.elements[name] = element
    end
  end
  self.state = nil
  self.fetchedAt = nil
  self.messageId = 0
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

  if self.state == nil and self.ws:isConnected() then
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
    self.state = data
    self:render()
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
        self.state = appliance
        self:render()
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
  self.messageId = self.messageId + 1
  self.ws:send(JSON:encode({ type = "update", name = self.name, message_id = self.messageId, data = data }))
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
  self:send({ fridge_target = math.floor(value + 0.5) })
end

function CustomDevice:onFreezerTarget(value)
  self:send({ freezer_target = math.floor(value + 0.5) })
end

function CustomDevice:onRapidCooling(value)
  self:send({ rapid_cooling = value })
end

function CustomDevice:onRapidFreezing(value)
  self:send({ rapid_freezing = value })
end

-- Commands for scenes and automations, e.g. virtual[ID]:call("start").
function CustomDevice:onCommand(command, arg)
  if command == "start" or command == "pause" or command == "stop" then
    self:send({ operation = command })
  elseif command == "power_on" or command == "power_off" then
    self:send({ power = command == "power_on" })
  elseif command == "set_fridge_target" and type(arg) == "number" then
    self:send({ fridge_target = math.floor(arg + 0.5) })
  elseif command == "set_freezer_target" and type(arg) == "number" then
    self:send({ freezer_target = math.floor(arg + 0.5) })
  elseif command == "set_rapid_cooling" and type(arg) == "boolean" then
    self:send({ rapid_cooling = arg })
  elseif command == "set_rapid_freezing" and type(arg) == "boolean" then
    self:send({ rapid_freezing = arg })
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
  return masculine and "Gotowy" or "Gotowa"
end

function CustomDevice:program(st)
  if st.kind == "washer" then
    local water = WATER_TEMPERATURES[st.water_temperature]
      or (st.water_temperature and st.water_temperature ~= "None" and st.water_temperature .. "°C")
    local spin = SPIN_LEVELS[st.spin_level] or (st.spin_level and st.spin_level .. " obr/min")
    local rinses = type(st.rinse_cycles) == "number" and string.format("płukania: %d", st.rinse_cycles) or nil
    return joined(st.course and ("Program " .. st.course), water, spin, rinses)
  elseif st.kind == "dryer" then
    local level = DRY_LEVELS[st.dry_level] and ("suszenie " .. DRY_LEVELS[st.dry_level]) or nil
    return joined(st.course and ("Program " .. st.course), level, st.wrinkle_prevent and "antyzagniecenia" or nil)
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
  local total = type(st.energy_kwh) == "number" and string.format("zużycie %.1f kWh", st.energy_kwh) or nil
  local text = joined(draw, total)
  return (text:gsub("^%l", string.upper))
end

function CustomDevice:temperatureText(st)
  if type(st.oven_target) ~= "number" or st.oven_target <= 0 then
    return joined(st.lamp and "Oświetlenie włączone" or nil)
  end
  return joined(
    string.format("Temperatura %s, zadana %s", temperature(st.oven_temperature), temperature(st.oven_target)),
    st.lamp and "oświetlenie włączone" or nil
  )
end

function CustomDevice:remote(st)
  if st.remote_control == false then
    return "Zdalne sterowanie wyłączone na panelu urządzenia"
  elseif st.remote_control == true then
    return "Zdalne sterowanie włączone"
  end
  return ""
end

function CustomDevice:setText(name, text)
  local element = self.elements[name]
  if element == nil then
    return
  end
  -- An empty text hides the element instead of leaving a blank line.
  element:setValue("visibility", text ~= "" and "visible" or "hidden_adjust")
  if text ~= "" then
    element:setValue("value", text, true)
  end
end

function CustomDevice:setControl(name, enabled, value)
  local element = self.elements[name]
  if element == nil then
    return
  end
  element:setValue("enabled", enabled)
  if value == nil then
    return
  end
  if element:getValue("type") == "slider" then
    value = utils.math:clamp(element:getValue("minimum"), element:getValue("maximum"), value)
  end
  element:setValue("value", value, true)
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
    self.elements.progress:setValue("visibility", active and "visible" or "hidden_adjust")
    self.elements.progress:setValue("value", utils.math:clamp(0, 100, progress), true)
  end

  if self.state ~= nil then
    self:setText("program", self:program(st))
    self:setText("remote", self:remote(st))
    self:setText("energy", self:energy(st))
    self:setText("doors", self:doors(st))
    self:setText("temperature", self:temperatureText(st))
  end

  self:setControl("power", online, type(st.power) == "boolean" and st.power or nil)
  self:setControl("start", online and not running)
  self:setControl("pause", online and running)
  self:setControl("stop", online and active)
  self:setControl("fridge_target", online, st.fridge_target)
  self:setControl("freezer_target", online, st.freezer_target)
  self:setControl("rapid_cooling", online, st.rapid_cooling)
  self:setControl("rapid_freezing", online, st.rapid_freezing)
end
