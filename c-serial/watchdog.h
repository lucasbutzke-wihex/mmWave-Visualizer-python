#ifndef WDT_H
#define WDT_H

#include <pthread.h>

typedef struct {
    double timeout;
    double last_heartbeat;
    int running;
    pthread_mutex_t lock;
    pthread_t thread_id;
    char pin[8];
} RadarWatchdog;

void watchdog_start(RadarWatchdog *wdt, const char *gpio_pin, double timeout_val);
void watchdog_feed(RadarWatchdog *wdt);
void watchdog_stop(RadarWatchdog *wdt);

#endif // WDT_H