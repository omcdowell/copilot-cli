function getArguments() {
    const args = process.argv.slice(2);

    if (args.length < 2) {
        console.error("Too few arguments. Please provide the username and password as arguments in the following format: 'user=<your_user> password=<your_password>'.");
        process.exit(1);
    }
    const user = getSingleArgument(args, "user");
    const password = getSingleArgument(args, "password");
    const debugMode = getOptionalArgument(args, "debugMode", "false");

    return {
        "user": user,
        "password": password,
        "debugMode": debugMode
    };
}

function getSingleArgument(args, argumentName) {
    const argNameToSearch = `${argumentName}=`;

    const arg = args.filter(a => a.includes(argNameToSearch));
    if (arg.length === 0) {
        console.error(`Argument ${argumentName} not found`);
        process.exit(1);
    }
    return arg[0].split("=").slice(1).join("=");
}

function getOptionalArgument(args, argumentName, defaultValue) {
    const argNameToSearch = `${argumentName}=`;
    const arg = args.filter(a => a.includes(argNameToSearch));
    if (arg.length === 0) {
        return defaultValue;
    }
    return arg[0].split("=").slice(1).join("=");
}

module.exports = {
    getArguments
};
