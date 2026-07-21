import time
import math
import struct
import datetime
import json_fix # import this anytime before the JSON.dumps gets called
import json
import numpy
json.fallback_table[numpy.ndarray] = lambda array: array.tolist()

import logging
log = logging.getLogger(__name__)

UART_MAGIC_WORD = bytearray(b'\x02\x01\x04\x03\x06\x05\x08\x07')

class UARTParser():
    def __init__(self, type):
        # Set this option to 1 to save UART output from the radar device
        self.saveBinary = 0
        self.replay = 0
        self.binData = bytearray(0)
        self.uartCounter = 0
        self.framesPerFile = 100
        self.first_file = True
        self.filepath = datetime.datetime.now().strftime("%m_%d_%Y_%H_%M_%S")
        self.parserType = type
        self.dataCom = None
        self.isLowPowerDevice = False
        self.frames = [] # TODO this needs to be reset if connection is reset
        self.comError = 0
        
        # Data storage
        self.now_time = datetime.datetime.now().strftime('%Y%m%d-%H%M')
    

    def readAndParseUartDoubleCOMPort(self, demo):
        
        self.fail = 0
        self.demo = demo
        if (self.replay):
            return self.replayHist()

        data = {'cfg': self.cfg, 'demo': self.demo, 'device': self.device}
    
        # Find magic word, and therefore the start of the frame
        index = 0
        magicByte = self.dataCom.read(1)
        frameData = bytearray(b'')
        while (1):
            # If the device doesn't transmit any data, the COMPort read function will eventually timeout
            # Which means magicByte will hold no data, and the call to magicByte[0] will produce an error
            # This check ensures we can give a meaningful error
            if (len(magicByte) < 1):
                log.error("ERROR: No data detected on COM Port, read timed out")
                log.error("\tBe sure that the device is in the proper mode, and that the cfg you are sending is valid")
                magicByte = self.dataCom.read(1)
                
            # Found matching byte
            elif (magicByte[0] == UART_MAGIC_WORD[index]):
                index += 1
                frameData.append(magicByte[0])
                if (index == 8): # Found the full magic word
                    break
                magicByte = self.dataCom.read(1)
                
            else:
                # When you fail, you need to compare your byte against that byte (ie the 4th) AS WELL AS compare it to the first byte of sequence
                # Therefore, we should only read a new byte if we are sure the current byte does not match the 1st byte of the magic word sequence
                if (index == 0): 
                    magicByte = self.dataCom.read(1)
                index = 0 # Reset index
                frameData = bytearray(b'') # Reset current frame data
        
        # Read in version from the header
        versionBytes = self.dataCom.read(4)
        
        frameData += bytearray(versionBytes)

        # Read in length from header
        lengthBytes = self.dataCom.read(4)
        frameData += bytearray(lengthBytes)
        frameLength = int.from_bytes(lengthBytes, byteorder='little')
        
        # Subtract bytes that have already been read, IE magic word, version, and length
        # This ensures that we only read the part of the frame in that we are lacking
        frameLength -= 16 

        # Read in rest of the frame
        frameData += bytearray(self.dataCom.read(frameLength))

        # frameData now contains an entire frame, send it to parser
        if (self.parserType == "DoubleCOMPort"):
            outputDict = self.parseStandardFrame(frameData, self.demo)
        else:
            log.error('FAILURE: Bad parserType')

        # If save binary is enabled
        if(self.saveBinary == 1):
            # Save data every framesPerFile frames
            self.uartCounter += 1

            # uncomment below to save bin data in Matlab-friendly format
            # self.binData += frameData
            # if (self.uartCounter % self.framesPerFile == 0):
            #     # First file requires the path to be set up
            #     if(self.first_file is True): 
            #         if(os.path.exists('binData/') == False):
            #             # Note that this will create the folder in the caller's path, not necessarily in the Industrial Viz Folder                        
            #             os.mkdir('binData/')
            #         os.mkdir('binData/'+self.filepath)
            #         self.first_file = False
            #     toSave = bytes(self.binData)
            #     fileName = 'binData/' + self.filepath + '/pHistBytes_' + str(math.floor(self.uartCounter/self.framesPerFile)) + '.bin'
            #     bfile = open(fileName, 'wb')
            #     bfile.write(toSave)
            #     bfile.close()
            #     # Reset binData and missed frames
            #     self.binData = []
 
            # Saving data here for replay
            frameJSON = {}
            frameJSON['frameData'] = outputDict
            frameJSON['timestamp'] = time.time() * 1000

            self.frames.append(frameJSON)
            data['data'] = self.frames

            # if (self.uartCounter % self.framesPerFile == 0):
            #     if(self.first_file is True): 
            #         if(os.path.exists('binData/') == False):
            #             # Note that this will create the folder in the caller's path, not necessarily in the viz folder            
            #             os.mkdir('binData/')
            #         os.mkdir('binData/'+self.filepath)
            #         self.first_file = False
            #     with open('./binData/'+self.filepath+'/replay_' + str(math.floor(self.uartCounter/self.framesPerFile)) + '.json', 'w') as fp:
            #         json_object = json.dumps(data, indent=4)
            #         fp.write(json_object)
            #         self.frames = [] # Uncomment to put data into one file at a time in 100 frame chunks
        
        return outputDict

    def parseStandardFrame(self, frameData, demo=None):
        # Constants for parsing frame header
        headerStruct = 'Q8I'

        if demo == DEMO_3DPT_6844:
            headerStruct = 'Q9I'

        frameHeaderLen = struct.calcsize(headerStruct)
        tlvHeaderLength = 8

        # Define the function's output structure and initialize error field to no error
        outputDict = {}
        outputDict['error'] = 0
        outputDict['demo'] = demo

        # A sum to track the frame packet length for verification for transmission integrity 
        totalLenCheck = 0   
        # Read in frame Header
        try:
            if demo == DEMO_3DPT_6844:
                magic, version, totalPacketLen, platform, frameNum, timeCPUCycles, numDetectedObj, numDetectedObjMinor, numTLVs, subFrameNum = struct.unpack(headerStruct, frameData[:frameHeaderLen])
            else:
                magic, version, totalPacketLen, platform, frameNum, timeCPUCycles, numDetectedObj, numTLVs, subFrameNum = struct.unpack(headerStruct, frameData[:frameHeaderLen])
            
        except:
            log.error('Error: Could not read frame header')
            outputDict['error'] = 1

        # Move frameData ptr to start of 1st TLV   
        frameData = frameData[frameHeaderLen:]
        totalLenCheck += frameHeaderLen

        if numDetectedObj > 10000:
            return outputDict

        # Save frame number to output
        outputDict['frameNum'] = frameNum

        # Initialize the point cloud struct since it is modified by multiple TLV's
        # Each point has the following: X, Y, Z, Doppler, SNR, Noise, Track index
        outputDict['pointCloud'] = np.zeros((numDetectedObj, 7), np.float64)
        # Initialize the track indexes to a value which indicates no track
        outputDict['pointCloud'][:, 6] = 255

        if demo == DEMO_3DPT_6844:
            outputDict['pointCloudMinor'] = np.zeros((numDetectedObjMinor, 7), np.float64)
            # Initialize the track indexes to a value which indicates no track
            outputDict['pointCloudMinor'][:, 6] = 255

        # Find and parse all TLV's
        # print(f"Number of TLVs: {numTLVs} \n")
        for i in range(numTLVs):
            try:
                tlvType, tlvLength = tlvHeaderDecode(frameData[:tlvHeaderLength])
                frameData = frameData[tlvHeaderLength:]
                totalLenCheck += tlvHeaderLength
                # print("tlvType: %d, tlvLength: %d" % (tlvType, tlvLength))
            except:
                log.warning('TLV Header Parsing Failure: Ignored frame due to parsing error')
                outputDict['error'] = 2
                return {}

            if (tlvType in parserFunctions):
                parserFunctions[tlvType](frameData[:tlvLength], tlvLength, outputDict)
            elif (tlvType in unusedTLVs):
                log.debug("No function to parse TLV type: %d" % (tlvType))
            else:
                log.info("Invalid TLV type: %d" % (tlvType))
                print("\n\nInvalid TLV type: %d\n\n" % (tlvType))
                print("\nDropping frame...")
                break

            # Move to next TLV
            frameData = frameData[tlvLength:]
            totalLenCheck += tlvLength
        
        # Pad totalLenCheck to the next largest multiple of 32
        # since the device does this to the totalPacketLen for transmission uniformity
        totalLenCheck = 32 * math.ceil(totalLenCheck / 32)

        # Verify the total packet length to detect transmission error that will cause subsequent frames to dropped
        if (totalLenCheck != totalPacketLen):
            if demo != DEMO_VITALS and demo != DEMO_3DPT_6844:
                log.warning('Frame packet length read is not equal to totalPacketLen in frame header. Subsequent frames may be dropped.')
            outputDict['error'] = 3
            
        # Run supplemental logic on TLV Data before saving to file
        classificationSupplement.run_frame(outputDict)

        # Debug print to show Radar TLV data in
        # print(outputDict)
        
        return outputDict
    
    def tlvHeaderDecode(data):
        tlvType, tlvLength = struct.unpack('2I', data)
        return tlvType, tlvLength