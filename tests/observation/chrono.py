"""Mesure de temps robuste à une machine chargée (plusieurs agents en parallèle).

Le meilleur de n passages : la charge n'ajoute que du temps, une vraie régression relève
aussi le minimum. Les seuils des tests restent fixes."""
import time


def meilleur(f, n=5):
    """(meilleur temps en secondes, résultat du dernier passage)."""
    temps, res = [], None
    for _ in range(n):
        t = time.perf_counter()
        res = f()
        temps.append(time.perf_counter() - t)
    return min(temps), res
