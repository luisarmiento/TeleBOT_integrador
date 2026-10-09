"""Carga explícita, transaccional y repetible: 15 clientes sintéticos, 30 líneas.

No se ejecuta al arrancar el bot. No borra ni reemplaza registros existentes.
Los identificadores son ejemplos, no identidades verificadas.
"""
from sqlalchemy import select, insert
from database import Repository, engine_config, clientes, lineas, planes, equipos, catalogo, deudas


def cargar(repo):
    with repo.engine.begin() as c:
        if c.execute(select(clientes.c.id).where(clientes.c.dni.like('000010%'))).first():
            return False
        if c.execute(select(planes.c.id)).first():
            raise ValueError('La carga requiere un catálogo vacío; no sobrescribe datos existentes.')
        plan_ids = []
        for name, price, detail in [('Básico 39.90', '39.90', '100 GB y llamadas nacionales.'),
                                    ('Plan 49.90', '49.90', '220 GB y llamadas nacionales.'),
                                    ('Ilimitado 65.90', '65.90', 'Datos y llamadas nacionales ilimitados.')]:
            plan_ids.append(c.execute(insert(planes).values(nombre=name, precio=price,
                descripcion=detail).returning(planes.c.id)).scalar_one())
        for name, price in [('Samsung A', '699.00'), ('Xiaomi B', '899.00'), ('Motorola C', '599.00')]:
            c.execute(insert(equipos).values(nombre=name, precio=price))
        for category, name, description, price, address in [
            ('PROMOCIONES', 'Portabilidad', 'Consulta las condiciones de portabilidad con un asesor.', None, False),
            ('PROMOCIONES', 'Equipos', 'Consulta disponibilidad y financiación de equipos.', None, False),
            ('PROMOCIONES', 'Recargas', 'Consulta las condiciones vigentes de recargas.', None, False),
            ('SERVICIOS', 'Fibra óptica', '250 Mbps. Instalación sujeta a evaluación de cobertura.', '69.00', True),
            ('SERVICIOS', 'Video', 'Suscripción de entretenimiento.', '15.00', False),
            ('SERVICIOS', 'Seguro móvil', 'Solicitud de cobertura para tu equipo, sujeta a evaluación.', '12.00', False),
            ('PAQUETES', 'Ti10', '5 GB por 7 días.', '10.00', False),
            ('PAQUETES', 'Redes', 'Paquete de redes sociales por 3 días.', '5.00', False),
            ('PAQUETES', 'Madrugador', '20 GB de 23:00 a 06:00.', '3.90', False)]:
            c.execute(insert(catalogo).values(categoria=category, nombre=name,
                descripcion=description, precio=price, requiere_direccion=address))
        for i in range(1, 16):
            client = c.execute(insert(clientes).values(dni=f'{1000+i:08d}',
                nombre=f'Cliente de prueba {i:02d}', telefono=f'98000{i:04d}')
                .returning(clientes.c.id)).scalar_one()
            for j in range(1 + (i - 1) // 5):
                plan = plan_ids[(i+j-1) % 3]
                line = repo.new_line(c, client, plan)
                if (i+j) % 3:
                    c.execute(insert(deudas).values(linea_id=line.id, importe='39.90',
                        vencimiento='2026-11-30', pagada=(i+j) % 3 == 2))
                    if (i+j) % 3 == 1:
                        c.execute(insert(deudas).values(linea_id=line.id, importe='10.00',
                            vencimiento='2026-12-31', pagada=False))
    return True


if __name__ == '__main__':
    engine = engine_config()
    try:
        print('Carga realizada.' if cargar(Repository(engine)) else 'Carga existente; no se duplicaron datos.')
    finally:
        engine.dispose()
