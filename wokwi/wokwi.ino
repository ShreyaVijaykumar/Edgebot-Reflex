/*
 * EdgeBot Reflex - Self-Contained ESP32 Firmware
 * ------------------------------------------------
 * ALL AI decision logic runs on the ESP32 itself.
 * No Python bridge needed for LED responses.
 *
 * Architecture:
 *   HC-SR04 --> [Mamba Reflex Layer] --> |
 *                                        |--> [Arbiter] --> LEDs
 *   HC-SR04 --> [SmolVLA Plan Layer] --> |
 *
 * Mamba reflex  : fires in <1ms, uses rolling distance history (SSM-style)
 * SmolVLA plan  : fires every 500ms, uses trend + goal reasoning
 * Arbiter       : Mamba wins when danger detected
 *
 * LED meanings:
 *   RED   = Mamba fired STOP (obstacle < 15cm)
 *   GREEN = Moving safely (Mamba FWD/LEFT/RIGHT)
 *   BLUE  = SmolVLA plan active (open space, goal-directed)
 *
 * Serial output: JSON frames for monitoring
 *   {"dist":42.3,"mamba":"FWD","plan":"PLAN_FWD","cmd":"PLAN_FWD","ts":1234}
 */

#define TRIG_PIN    26
#define ECHO_PIN    27
#define LED_DANGER  2
#define LED_OK      4
#define LED_PLAN    5

#define DANGER_CM   15.0
#define CAUTION_CM  30.0
#define SENSOR_MS   50
#define SMOLVLA_MS  500
#define HISTORY_LEN 10

float distHistory[HISTORY_LEN];
int   histIdx    = 0;
int   histCount  = 0;

unsigned long lastSensorMs  = 0;
unsigned long lastSmolVLAMs = 0;

String mambaCmd  = "FWD";
String planCmd   = "PLAN_FWD";
String finalCmd  = "FWD";

unsigned long cmdStartMs = 0;
String        blinkState = "";

// ── Measure distance ────────────────────────────────────────────
float measureDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long d = pulseIn(ECHO_PIN, HIGH, 30000UL);
  if (d == 0) return 400.0;
  return (float)d * 0.034f / 2.0f;
}

// ── Add to rolling history ───────────────────────────────────────
void pushHistory(float dist) {
  distHistory[histIdx] = dist;
  histIdx = (histIdx + 1) % HISTORY_LEN;
  if (histCount < HISTORY_LEN) histCount++;
}

// ── Get history value i steps ago (0 = newest) ──────────────────
float historyAt(int stepsAgo) {
  if (stepsAgo >= histCount) return 400.0;
  int i = (histIdx - 1 - stepsAgo + HISTORY_LEN) % HISTORY_LEN;
  return distHistory[i];
}

// ── Trend: is distance decreasing (approaching)? ────────────────
bool isApproaching() {
  if (histCount < 4) return false;
  return historyAt(0) < historyAt(3);
}

// ================================================================
// MAMBA REFLEX LAYER
// Mimics Falcon Mamba SSM: processes rolling sensor history,
// constant-time decision regardless of history length.
// Fires every 50ms.
// ================================================================
String mambaReflex(float dist) {
  if (dist < DANGER_CM) {
    return "STOP";
  }
  if (dist < CAUTION_CM) {
    if (isApproaching()) {
      // SSM trend detection: pick turn direction from history pattern
      float recent = historyAt(0);
      float older  = historyAt(3);
      if ((recent - older) < -5.0) {
        return "LEFT";
      }
      return "RIGHT";
    }
    return "FWD";
  }
  return "FWD";
}

// ================================================================
// SMOLVLA PLANNING LAYER
// Mimics SmolVLA: goal-directed, fires every 500ms.
// Uses semantic reasoning: "navigate forward, avoid obstacles"
// In real system: camera frame + text goal -> action vector
// ================================================================
String smolvlaPlan(float dist) {
  if (dist < DANGER_CM) {
    return "PLAN_STOP";
  }
  if (dist < CAUTION_CM) {
    if (isApproaching()) {
      return "PLAN_LEFT";
    }
    return "PLAN_FWD";
  }
  // Open space: full speed ahead toward goal
  return "PLAN_FWD";
}

// ================================================================
// PRIORITY ARBITER
// Mamba overrides SmolVLA in danger/caution zones.
// SmolVLA leads in open space (goal-directed behaviour).
// ================================================================
String arbitrate(float dist, String mamba, String plan) {
  if (mamba == "STOP")    return "STOP";
  if (dist < CAUTION_CM)  return mamba;
  return plan;
}

// ── Apply final command to LEDs ──────────────────────────────────
void applyLEDs(String cmd) {
  if (cmd == "STOP") {
    digitalWrite(LED_DANGER, HIGH);
    digitalWrite(LED_OK,     LOW);
    digitalWrite(LED_PLAN,   LOW);
  } else if (cmd == "FWD" || cmd == "LEFT" || cmd == "RIGHT") {
    digitalWrite(LED_DANGER, LOW);
    digitalWrite(LED_OK,     HIGH);
    digitalWrite(LED_PLAN,   LOW);
  } else if (cmd.length() >= 5 && cmd.substring(0, 5) == "PLAN_") {
    digitalWrite(LED_DANGER, LOW);
    digitalWrite(LED_OK,     LOW);
    digitalWrite(LED_PLAN,   HIGH);
  }
}

// ── Setup ────────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);
  pinMode(TRIG_PIN,   OUTPUT);
  pinMode(ECHO_PIN,   INPUT);
  pinMode(LED_DANGER, OUTPUT);
  pinMode(LED_OK,     OUTPUT);
  pinMode(LED_PLAN,   OUTPUT);

  // Startup blink: RED -> GREEN -> BLUE to show all LEDs work
  digitalWrite(LED_DANGER, HIGH); delay(300); digitalWrite(LED_DANGER, LOW);
  digitalWrite(LED_OK,     HIGH); delay(300); digitalWrite(LED_OK,     LOW);
  digitalWrite(LED_PLAN,   HIGH); delay(300); digitalWrite(LED_PLAN,   LOW);

  Serial.println("{\"status\":\"ready\",\"firmware\":\"EdgeBotReflex-v2-selfcontained\"}");
}

// ── Main loop ────────────────────────────────────────────────────
void loop() {
  unsigned long now = millis();

  // --- Sensor read every 50ms (Mamba reflex rate) ---------------
  if (now - lastSensorMs >= SENSOR_MS) {
    lastSensorMs = now;

    float dist = measureDistanceCm();
    pushHistory(dist);

    // Run Mamba reflex (fast path - always runs)
    mambaCmd = mambaReflex(dist);

    // Run SmolVLA plan (slow path - every 500ms)
    if (now - lastSmolVLAMs >= SMOLVLA_MS) {
      lastSmolVLAMs = now;
      planCmd = smolvlaPlan(dist);
    }

    // Arbitrate
    finalCmd = arbitrate(dist, mambaCmd, planCmd);

    // Apply to LEDs immediately
    applyLEDs(finalCmd);

    // Serial output for monitoring
    Serial.print("{\"dist\":");
    Serial.print(dist, 1);
    Serial.print(",\"mamba\":\"");
    Serial.print(mambaCmd);
    Serial.print("\",\"plan\":\"");
    Serial.print(planCmd);
    Serial.print("\",\"cmd\":\"");
    Serial.print(finalCmd);
    Serial.print("\",\"ts\":");
    Serial.print(now);
    Serial.println("}");
  }
}
