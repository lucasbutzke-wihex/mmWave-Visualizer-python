#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <pthread.h>
#include <sys/time.h>
#include <fcntl.h>
#include <string.h>

#include "watchdog.h"

void _gpio_export(const char *pin) // ativa pino
{
    int fd = open("/sys/class/gpio/export", O_WRONLY);

    if (fd != -1) 
    { 
        write(fd, pin, strlen(pin)); 
        close(fd); 
    }
}

void _gpio_set_direction(const char *pin, const char *dir) //define como input/output
{
    char path[50];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%s/direction", pin);
    int fd = open(path, O_WRONLY);

    if (fd != -1) 
    { 
        write(fd, dir, strlen(dir)); 
        close(fd); 
    }
}

void _gpio_write(const char *pin, const char *value) 
{
    char path[50];
    snprintf(path, sizeof(path), "/sys/class/gpio/gpio%s/value", pin);
    int fd = open(path, O_WRONLY);

    if (fd != -1) 
    { 
        write(fd, value, strlen(value)); 
        close(fd); 
    }
}

double _get_current_time() // retorna tempo atual (s)
{
    struct timeval tv;
    gettimeofday(&tv, NULL);

    return (double)tv.tv_sec + (double)tv.tv_usec / 1000000.0;
}

void watchdog_feed(RadarWatchdog *wdt) //grava tempo da ultima comunicação
{
    pthread_mutex_lock(&wdt->lock);
    wdt->last_heartbeat = _get_current_time();
    pthread_mutex_unlock(&wdt->lock);
}

void _watchdog_force_reset(const char *pin) 
{
    printf("[WATCHDOG] !!! Alerta: 1s sem comunicação. Resetando radar !!!\n");
    
    _gpio_write(pin, "0");  // nRESET em LOW  -> Ativa Reset
    usleep(100000);               // Espera 100ms
    _gpio_write(pin, "1");  // nRESET em HIGH -> Libera Radar
    
    printf("[WATCHDOG] reset enviado com sucesso\n");
}

void* _watchdog_monitor(void *arg) 
{
    RadarWatchdog *wdt = (RadarWatchdog*)arg;
    
    while (wdt->running) 
    {
        usleep(100000); // Checa o status a cada 100ms
        
        pthread_mutex_lock(&wdt->lock);
        double time_since_last_feed = _get_current_time() - wdt->last_heartbeat;
        pthread_mutex_unlock(&wdt->lock);
        
        if (time_since_last_feed > wdt->timeout) 
        {
            _watchdog_force_reset(wdt->pin);
            
            pthread_mutex_lock(&wdt->lock);
            wdt->last_heartbeat = _get_current_time() + 3.0; //3s ate proximo reset ser possivel
            pthread_mutex_unlock(&wdt->lock);
        }
    }

    return NULL;
}

void watchdog_start(RadarWatchdog *wdt, const char *gpio_pin, double timeout_val) {
    strncpy(wdt->pin, gpio_pin, sizeof(wdt->pin) - 1);

    _gpio_export(wdt->pin);
    usleep(50000); // pausa para o criar os arquivos do sysfs
    _gpio_set_direction(wdt->pin, "out");
    _gpio_write(wdt->pin, "1"); 

    // Inicializa a estrutura
    wdt->timeout = timeout_val;
    wdt->last_heartbeat = _get_current_time();
    wdt->running = 1;
    pthread_mutex_init(&wdt->lock, NULL);
    
    // Cria a thread de background
    pthread_create(&wdt->thread_id, NULL, _watchdog_monitor, (void*)wdt);
}

void watchdog_stop(RadarWatchdog *wdt) 
{
    wdt->running = 0;
    pthread_join(wdt->thread_id, NULL); // espera a thread finalizar
    pthread_mutex_destroy(&wdt->lock);
    printf("[WATCHDOG] Monitor parado\n");
}