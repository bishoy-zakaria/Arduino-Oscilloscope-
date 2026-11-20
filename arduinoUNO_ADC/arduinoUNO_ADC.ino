#include <Arduino.h>
#include <math.h>

constexpr uint16_t SAMPLES_PER_BUF = 100;
constexpr uint32_t BAUD_RATE = 1000000;
constexpr uint32_t MCU_CLOCK_HZ = 16000000UL;

// Timer2 ADC trigger parameters (40 us / 25 kHz)
constexpr uint16_t ADC_TIMER_PRESCALER = 8;
constexpr uint8_t  ADC_TIMER_OCR2A = 79;

// Live Timer1 PWM state (updated by setPWM() and sent in each packet)
volatile uint16_t g_pwm_prescaler = 1;
volatile uint16_t g_pwm_icr1 = 7999;
volatile uint16_t g_pwm_ocr1a = 1600;

struct __attribute__((packed)) AdcPacket {
  uint32_t timestamp_us;
  uint32_t f_cpu_hz;
  uint16_t pwm_icr1;
  uint16_t pwm_ocr1a;
  uint16_t pwm_prescaler;
  uint8_t  adc_ocr2a;
  uint16_t adc_prescaler;
  uint16_t samples[SAMPLES_PER_BUF];
};

volatile uint16_t buffers[2][SAMPLES_PER_BUF];
volatile uint32_t endTimestampsUs[2] = {0, 0};
volatile uint8_t activeBuf = 0;
volatile uint16_t sampleIdx = 0;

volatile int8_t readyBuf = -1;
volatile uint32_t overrunCount = 0;

// Non-blocking serial command buffer for on-the-fly PWM updates
char g_cmdBuf[32];
uint8_t g_cmdIdx = 0;

// Triggered every 40 us by Timer2 (2 MHz / 80 = 25 kHz)
ISR(TIMER2_COMPA_vect) {
  ADCSRA |= (1 << ADSC);
}

// Triggered when each ADC conversion completes (~13 us after start)
ISR(ADC_vect) {
  uint16_t val = ADC;
  buffers[activeBuf][sampleIdx++] = val;

  if (sampleIdx >= SAMPLES_PER_BUF) {
    endTimestampsUs[activeBuf] = micros();
    sampleIdx = 0;

    uint8_t completed = activeBuf;
    activeBuf ^= 1; // Swap to the other half of the double buffer

    if (readyBuf == -1) {
      readyBuf = completed;
    } else {
      overrunCount++;
    }
  }
}

static uint8_t prescalerToCs1Bits(uint16_t prescaler) {
  switch (prescaler) {
    case 1:    return (1 << CS10);
    case 8:    return (1 << CS11);
    case 64:   return (1 << CS11) | (1 << CS10);
    case 256:  return (1 << CS12);
    case 1024: return (1 << CS12) | (1 << CS10);
    default:   return (1 << CS10);
  }
}

/**
 * PWM API on Digital Pin 9 (OC1A) using Timer1 Fast PWM Mode 14 (TOP = ICR1).
 *
 * @param freq_hz   Desired PWM frequency in Hz (e.g., 10.0 to 100000.0)
 * @param duty_pct  Desired duty cycle in percent [0.0 .. 100.0]
 */
bool setPWM(float freq_hz, float duty_pct) {
  if (!(freq_hz > 0.0f) || isinf(freq_hz) || isnan(freq_hz)) {
    return false;
  }
  if (isnan(duty_pct) || isinf(duty_pct)) {
    return false;
  }

  // Clamp duty cycle to [0.0, 100.0]%
  if (duty_pct < 0.0f) duty_pct = 0.0f;
  if (duty_pct > 100.0f) duty_pct = 100.0f;

  constexpr uint16_t prescalers[] = {1, 8, 64, 256, 1024};
  uint16_t chosen_psc = 0;
  uint32_t chosen_top = 0;

  // Pick the smallest prescaler that keeps TOP (ICR1) within [1, 65535]
  for (uint8_t i = 0; i < (sizeof(prescalers) / sizeof(prescalers[0])); i++) {
    uint16_t psc = prescalers[i];
    double top_exact = (static_cast<double>(MCU_CLOCK_HZ) /
                        (static_cast<double>(psc) * static_cast<double>(freq_hz))) - 1.0;

    if (top_exact >= 1.0 && top_exact <= 65535.0) {
      chosen_psc = psc;
      chosen_top = static_cast<uint32_t>(lround(top_exact));
      break;
    }
  }

  // Fallback clamping if requested frequency is outside achievable range
  if (chosen_psc == 0) {
    double max_top = (static_cast<double>(MCU_CLOCK_HZ) /
                      (1.0 * static_cast<double>(freq_hz))) - 1.0;
    if (max_top > 65535.0) {
      chosen_psc = 1024;
      double min_top = (static_cast<double>(MCU_CLOCK_HZ) /
                        (1024.0 * static_cast<double>(freq_hz))) - 1.0;
      long rounded_min = lround(min_top);
      if (rounded_min < 1L) rounded_min = 1L;
      if (rounded_min > 65535L) rounded_min = 65535L;
      chosen_top = static_cast<uint32_t>(rounded_min);
    } else {
      chosen_psc = 1;
      chosen_top = 1;
    }
  }

  uint16_t icr_val = static_cast<uint16_t>(chosen_top);
  uint32_t period_ticks = static_cast<uint32_t>(icr_val) + 1UL;

  // Compute OCR1A ticks for requested duty cycle
  double ocr_exact = (static_cast<double>(duty_pct) / 100.0) * static_cast<double>(period_ticks);
  uint32_t ocr_val = (ocr_exact <= 0.0) ? 0UL : static_cast<uint32_t>(lround(ocr_exact));

  uint8_t cs_bits = prescalerToCs1Bits(chosen_psc);

  cli();
  // BUG FIX 1: Ensure Pin 9 physical push-pull output driver is enabled in DDRB
  pinMode(9, OUTPUT);

  // Configure Mode 14 (Fast PWM, TOP = ICR1): WGM13:0 = 1110
  TCCR1A = (1 << WGM11);
  TCCR1B = (1 << WGM13) | (1 << WGM12);

  // BUG FIX 2 & 3: Clean glitch-free 0% and 100% DC handling
  if (duty_pct <= 0.0f) {
    // 0% Duty: Disconnect OC1A and drive Pin 9 LOW continuously
    TCCR1A &= ~(1 << COM1A1);
    digitalWrite(9, LOW);
    ocr_val = 0;
  } else if (duty_pct >= 100.0f) {
    // 100% Duty: Disconnect OC1A and drive Pin 9 HIGH continuously (eliminates 1-clock reset glitch)
    TCCR1A &= ~(1 << COM1A1);
    digitalWrite(9, HIGH);
    ocr_val = period_ticks;
  } else {
    // Non-inverting Fast PWM on OC1A (Pin 9)
    TCCR1A |= (1 << COM1A1);
    if (ocr_val >= period_ticks) {
      ocr_val = period_ticks - 1;
    }
  }

  ICR1 = icr_val;
  OCR1A = static_cast<uint16_t>(ocr_val);

  // Reset counter if needed so new TOP doesn't cause a delayed wrap
  if (TCNT1 > icr_val) {
    TCNT1 = 0;
  }

  // Start/update clock prescaler
  TCCR1B = (TCCR1B & ~((1 << CS12) | (1 << CS11) | (1 << CS10))) | cs_bits;

  // Atomic snapshot of live registers for packet telemetry
  g_pwm_prescaler = chosen_psc;
  g_pwm_icr1 = icr_val;
  g_pwm_ocr1a = static_cast<uint16_t>(ocr_val);
  sei();

  return true;
}

void setupADC_Trigger_Timer2() {
  cli();
  // ADC on A0 (MUX = 0), AVcc reference (REFS0 = 1)
  ADMUX = (1 << REFS0);
  DIDR0 |= (1 << ADC0D);

  // ADC enable, ADC interrupt enable, prescaler = 16 (1 MHz ADC clock)
  ADCSRA = (1 << ADEN) | (1 << ADIE) | (1 << ADPS2);

  // Timer2 CTC mode, prescaler = 8 (2 MHz -> 0.5 us/tick)
  TCCR2A = 0;
  TCCR2B = 0;
  TCNT2  = 0;
  TCCR2A |= (1 << WGM21);
  TCCR2B |= (1 << CS21);
  OCR2A = ADC_TIMER_OCR2A; // (79 + 1) * 0.5 us = 40.0 us
  TIMSK2 |= (1 << OCIE2A);
  sei();
}

/**
 * Non-blocking serial command handler:
 * Allows user or Python app to set PWM frequency and duty cycle on the fly!
 * Formats supported:
 *   "F:400,D:50\n"
 *   "SET,400,50\n"
 *   "400,50\n"
 */
void handleSerialCommands() {
  while (Serial.available() > 0) {
    char c = static_cast<char>(Serial.read());
    if (c == '\n' || c == '\r') {
      if (g_cmdIdx > 0) {
        g_cmdBuf[g_cmdIdx] = '\0';
        float f = 0.0f;
        float d = 0.0f;

        // Reliable parsing compatible with all AVR GCC environments without needing -lscanf_flt
        char *pF = strchr(g_cmdBuf, 'F');
        char *pD = strchr(g_cmdBuf, 'D');
        if (pF && pD) {
          f = static_cast<float>(atof(pF + 2));
          d = static_cast<float>(atof(pD + 2));
        } else {
          char *comma = strchr(g_cmdBuf, ',');
          if (comma) {
            *comma = '\0';
            f = static_cast<float>(atof(g_cmdBuf));
            d = static_cast<float>(atof(comma + 1));
          }
        }

        if (f > 0.0f && d >= 0.0f && d <= 100.0f) {
          setPWM(f, d);
        }
        g_cmdIdx = 0;
      }
    } else if (g_cmdIdx < sizeof(g_cmdBuf) - 1) {
      g_cmdBuf[g_cmdIdx++] = c;
    }
  }
}

void setup() {
  pinMode(9, OUTPUT); // Enable Timer1 OC1A push-pull output driver
  Serial.begin(BAUD_RATE);
  setupADC_Trigger_Timer2();

  // Active PWM output: 2000 Hz, 10.0% duty cycle on Pin 9
  // (Change via serial command or call setPWM(freq, duty) as needed)
  setPWM(2000.0f, 20.0f);
}

void loop() {
  // Check for incoming dynamic setPWM commands without blocking
  handleSerialCommands();

  int8_t bufToSend = -1;
  uint32_t ts = 0;
  uint16_t psc_snap = 0;
  uint16_t icr_snap = 0;
  uint16_t ocr_snap = 0;

  noInterrupts();
  if (readyBuf != -1) {
    bufToSend = readyBuf;
    ts = endTimestampsUs[bufToSend];
    psc_snap = g_pwm_prescaler;
    icr_snap = g_pwm_icr1;
    ocr_snap = g_pwm_ocr1a;
    readyBuf = -1;
  }
  interrupts();

  if (bufToSend != -1) {
    AdcPacket pkt;
    pkt.timestamp_us = ts;
    pkt.f_cpu_hz = MCU_CLOCK_HZ;
    pkt.pwm_icr1 = icr_snap;
    pkt.pwm_ocr1a = ocr_snap;
    pkt.pwm_prescaler = psc_snap;
    pkt.adc_ocr2a = ADC_TIMER_OCR2A;
    pkt.adc_prescaler = ADC_TIMER_PRESCALER;

    for (uint16_t i = 0; i < SAMPLES_PER_BUF; i++) {
      pkt.samples[i] = buffers[bufToSend][i];
    }

    Serial.write(0xAA);
    Serial.write(0x55);
    Serial.write(reinterpret_cast<const uint8_t*>(&pkt), sizeof(pkt));
  }
}
