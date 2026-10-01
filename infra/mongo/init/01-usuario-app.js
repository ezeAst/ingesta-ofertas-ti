// Se ejecuta una sola vez, cuando el volumen de datos está vacío.
// Crea el usuario de la aplicación con permisos solo sobre su base y la de pruebas
// (mínimo privilegio): la aplicación nunca usa la cuenta de administrador.
const bd = process.env.MONGO_BD;
const bdPruebas = `${bd}_pruebas`;

db.getSiblingDB(bd).createUser({
  user: process.env.MONGO_APP_USUARIO,
  pwd: process.env.MONGO_APP_CLAVE,
  roles: [
    { role: "readWrite", db: bd },
    { role: "dbAdmin", db: bd }, // collMod: actualizar el validador $jsonSchema
    { role: "readWrite", db: bdPruebas },
    { role: "dbAdmin", db: bdPruebas },
  ],
});
